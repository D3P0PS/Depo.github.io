"""Cache persistente delle statistiche extra (cartellini) per squadra, da SofaScore.

Il piano gratuito di RapidAPI ha un budget limitato: non ci si puo' permettere
di riscaricare lo storico di una squadra ad ogni corsa. Questa cache vive su
disco e sopravvive fra le corse, e ogni voce porta la data del suo ultimo
aggiornamento — il report mostra sempre quanto e' vecchio un dato invece di
spacciarlo per fresco. Oltre STALE_AFTER_DAYS l'informazione resta visibile
ma marcata come vecchia, e viene aggiornata con priorita' alla prossima
corsa che ha budget disponibile.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, Optional

#: una squadra gioca all'incirca una volta a settimana: oltre questa soglia
#: la media rischia di non riflettere piu' la forma/rosa attuale (infortuni,
#: cambio di modulo, ...). Il dato resta comunque mostrato, solo segnalato.
STALE_AFTER_DAYS = 7.0

CACHE_FILENAME = "sofascore_team_cards.json"


@dataclass
class TeamCardStats:
    team_id: int
    team_name: str
    updated_at: str          # ISO 8601 UTC, es. "2026-08-30T14:22:00+00:00"
    matches_used: int
    yellow_avg: float        # cartellini gialli ricevuti, media sulle ultime partite
    red_avg: float           # cartellini rossi ricevuti, media sulle ultime partite

    def age_days(self, now: Optional[dt.datetime] = None) -> float:
        now = now or dt.datetime.now(dt.timezone.utc)
        updated = dt.datetime.fromisoformat(self.updated_at)
        return (now - updated).total_seconds() / 86400.0

    def is_stale(self, now: Optional[dt.datetime] = None) -> bool:
        return self.age_days(now) > STALE_AFTER_DAYS


def _cache_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, CACHE_FILENAME)


def load_cache(cache_dir: str) -> Dict[int, TeamCardStats]:
    path = _cache_path(cache_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    out: Dict[int, TeamCardStats] = {}
    for key, value in raw.items():
        try:
            out[int(key)] = TeamCardStats(**value)
        except (TypeError, ValueError):
            continue  # voce corrotta: si ignora, verra' ricostruita al bisogno
    return out


def save_cache(cache_dir: str, data: Dict[int, TeamCardStats]) -> None:
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(_cache_path(cache_dir), "w", encoding="utf-8") as fh:
            json.dump({str(k): asdict(v) for k, v in data.items()}, fh, indent=2)
    except OSError:
        pass  # una cache non scrivibile non deve far fallire l'analisi
