"""Client HTTP minimale (solo stdlib) con cache su disco e rate limiting.

La cache serve a due scopi:
  * non bruciare il budget di The Odds API (~500 richieste/mese sul free);
  * rispettare il limite di 10 richieste/minuto di football-data.org.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

DEFAULT_CACHE_DIR = os.environ.get(
    "FBEDGE_CACHE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "football-edge"),
)
USER_AGENT = "football-edge/1.0 (+stdlib urllib)"


class HttpError(RuntimeError):
    def __init__(self, status: int, url: str, body: str):
        self.status = status
        self.url = _redact(url)
        self.body = body
        super().__init__(f"HTTP {status} su {self.url}: {body[:300]}")


#: parametri che contengono un segreto. Solo questi: la funzione serve anche a
#: calcolare la chiave di cache, e mascherare un parametro qualsiasi (es. "key")
#: farebbe collassare richieste diverse sulla stessa voce.
SECRET_PARAMS = "apikey|api_key|api-key|token|access_token|secret|auth"


def redact(url: str) -> str:
    """Non far mai finire una API key nei log, negli errori o nei dump."""
    return re.sub(rf"(?i)\b({SECRET_PARAMS})=[^&]*", r"\1=***", url)


#: alias storico, usato internamente
_redact = redact


@dataclass
class Response:
    status: int
    headers: Dict[str, str]
    body: str
    from_cache: bool

    def json(self) -> Any:
        return json.loads(self.body)


class RateLimiter:
    """Finestra scorrevole: al massimo `limit` chiamate ogni `window` secondi."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._calls: list[float] = []

    def wait(self) -> None:
        if self.limit <= 0:
            return
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t < self.window]
        if len(self._calls) >= self.limit:
            sleep_for = self.window - (now - self._calls[0]) + 0.25
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
            self._calls = [t for t in self._calls if now - t < self.window]
        self._calls.append(time.monotonic())


class HttpClient:
    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        offline: bool = False,
        rate_limiter: Optional[RateLimiter] = None,
        timeout: float = 30.0,
        verbose: bool = False,
    ):
        self.cache_dir = cache_dir
        self.offline = offline
        self.rate_limiter = rate_limiter
        self.timeout = timeout
        self.verbose = verbose
        self.network_calls = 0
        self.cache_hits = 0
        os.makedirs(self.cache_dir, exist_ok=True)

    # ------------------------------------------------------------------ cache
    def _cache_path(self, url: str) -> str:
        key = hashlib.sha256(_redact(url).encode("utf-8")).hexdigest()[:32]
        return os.path.join(self.cache_dir, f"{key}.json")

    def _read_cache(self, url: str, ttl: int) -> Optional[Response]:
        path = self._cache_path(url)
        if not os.path.exists(path):
            return None
        age = time.time() - os.path.getmtime(path)
        if not self.offline and age > ttl:
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
        except (OSError, ValueError):
            return None
        return Response(blob["status"], blob["headers"], blob["body"], from_cache=True)

    def _write_cache(self, url: str, resp: Response) -> None:
        try:
            with open(self._cache_path(url), "w", encoding="utf-8") as fh:
                json.dump(
                    {"status": resp.status, "headers": resp.headers, "body": resp.body},
                    fh,
                )
        except OSError:
            pass  # una cache non scrivibile non deve far fallire l'analisi

    # ------------------------------------------------------------------- http
    def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        ttl: int = 3600,
        retries: int = 3,
    ) -> Response:
        cached = self._read_cache(url, ttl)
        if cached is not None:
            self.cache_hits += 1
            if self.verbose:
                print(f"  [cache] {_redact(url)}")
            return cached

        if self.offline:
            raise HttpError(0, url, "modalita' offline e nessuna copia in cache")

        req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        req_headers.update(headers or {})

        last_error: Optional[Exception] = None
        for attempt in range(retries):
            if self.rate_limiter:
                self.rate_limiter.wait()
            request = urllib.request.Request(url, headers=req_headers, method="GET")
            try:
                self.network_calls += 1
                if self.verbose:
                    print(f"  [net]   {_redact(url)}")
                with urllib.request.urlopen(request, timeout=self.timeout) as raw:
                    body = raw.read().decode("utf-8", errors="replace")
                    resp = Response(
                        raw.status,
                        {k.lower(): v for k, v in raw.headers.items()},
                        body,
                        from_cache=False,
                    )
                self._write_cache(url, resp)
                return resp
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429 and attempt < retries - 1:
                    time.sleep(min(60.0, 6.0 * (2 ** attempt)))
                    last_error = exc
                    continue
                # 4xx non recuperabili: propaga subito con il corpo della risposta
                raise HttpError(exc.code, url, body) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(2.0 * (2 ** attempt))
                    continue
        raise HttpError(0, url, f"errore di rete: {last_error}")


def build_url(base: str, params: Dict[str, Any]) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    return f"{base}?{urllib.parse.urlencode(clean)}" if clean else base
