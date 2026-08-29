# football-edge

Confronta le probabilità di un modello statistico con le quote reali di più
bookmaker e stima un *edge* per ogni mercato, con intervallo di incertezza.

**Non è un generatore di pronostici.** Nessuna riga dell'output è presentata
come sicura o garantita: ogni riga mostra una probabilità, la probabilità
implicita di mercato depurata dal margine, e un margine d'errore. I limiti del
modello vengono stampati a ogni esecuzione.

## Fonti dati

Solo API pubbliche e documentate. Nessuno scraping di siti di bookmaker.

| Fonte | Uso | Piano gratuito |
|---|---|---|
| [football-data.org](https://www.football-data.org/) v4 | calendario, risultati, forma | 10 richieste/minuto, prime divisioni europee + Championship |
| [The Odds API](https://the-odds-api.com/) v4 | quote 1X2, Over/Under, BTTS da più bookmaker (bet365 incluso nella regione `eu`) | ~500 crediti/mese |

Le seconde divisioni (Serie B, 2. Bundesliga, LaLiga2, Ligue 2) non sono nel
piano gratuito di football-data.org: vengono tentate e, in caso di `403`,
saltate con un messaggio esplicito nel riepilogo.

## Chiavi API

Entrambe gratuite, registrazione in un minuto:

```bash
export FOOTBALL_DATA_API_KEY="..."   # https://www.football-data.org/client/register
export ODDS_API_KEY="..."            # https://the-odds-api.com/#get-access
```

In alternativa `--football-data-key` / `--odds-key`, oppure un file passato con
`--env-file`. Senza chiave quote si può usare `--model-only`: si ottengono le
probabilità del modello, ma nessun edge (senza quote non c'è niente con cui
confrontarsi).

## Uso

```bash
python3 edge_scan.py --self-test                      # verifica il modello, nessuna rete
python3 edge_scan.py --date today                     # partite di oggi, 5 campionati principali
python3 edge_scan.py --competitions SA,PL --days 2    # due giorni, Serie A + Premier
python3 edge_scan.py --min-edge 3 --csv edge.csv      # solo edge >= 3%, esporta in CSV
python3 edge_scan.py --bookmakers bet365,pinnacle     # limita i bookmaker interrogati
```

Nessuna dipendenza esterna: solo la libreria standard di Python 3.9+.

Codici competizione: `SA PL BL1 PD FL1 DED PPL CL ELC SB BL2 SD FL2` (oppure `all`).

## Come funziona

1. **Forma.** Per ogni squadra si prendono le ultime `--form-matches` partite
   (default 10) separando casa e trasferta, con peso a decadimento esponenziale
   (`--half-life`, default 60 giorni: una partita di due mesi fa pesa la metà di
   una di ieri).
2. **Shrinkage a due livelli.** Il valore casa/trasferta viene tirato verso la
   forza complessiva della squadra, che a sua volta è tirata verso la media di
   lega. Serve a evitare che 3 partite di una neopromossa producano stime
   estreme: con pochi dati il risultato tende alla media, non al rumore.
3. **Gol attesi.** `λ_casa = media_gol_casa_lega × attacco_casa × difesa_trasferta`
   (e simmetrico per la trasferta).
4. **Poisson bivariato** (Karlis–Ntzoufras): due punteggi con una componente
   comune `λ₃` (`--lambda-cov`, default 0.12) che introduce la correlazione
   positiva osservata fra i gol delle due squadre. Con `--lambda-cov 0` si
   ricade nel Poisson indipendente.
5. **Mercato.** Le quote di ogni bookmaker vengono depurate dal margine
   (overround) *individualmente* e poi mediate — mediare le quote lorde
   sarebbe scorretto perché i margini variano molto fra operatori. Metodo di
   default: [Shin](https://doi.org/10.2307/2234526) (`--devig shin`), in
   alternativa `multiplicative` o `power`.
6. **Edge.** `edge% = probabilità_modello × quota_migliore − 1`. La quota usata
   è la migliore disponibile fra i bookmaker interrogati; la colonna `P.MKT` è
   il consenso equo di tutti.
7. **Incertezza.** Monte Carlo sui λ stimati (`--mc-draws`), da cui l'intervallo
   al 90% (`--ci`) su probabilità ed edge.

### Opzioni che vale la pena conoscere

| Opzione | Effetto |
|---|---|
| `--market-blend 0.3` | mescola la probabilità del modello con quella di mercato. Riduce l'eccesso di fiducia nel modello: consigliato se si prende sul serio l'output |
| `--half-life 30` | più reattivo ai cambi di forma, più rumoroso |
| `--form-matches 6` | finestra più corta, come da letteratura sulla forma recente |
| `--offline` | usa solo la cache locale, zero chiamate di rete |
| `--btts` | tenta anche il mercato BTTS (richiede un piano a pagamento di The Odds API; in caso di rifiuto degrada da solo) |

## Consumo delle API

Le risposte sono in cache su disco (`~/.cache/football-edge`, override con
`--cache-dir`): 15 minuti per le quote, 1 ora per il calendario, 6 ore per lo
storico. Un'esecuzione su 5 campionati costa circa 5 chiamate a football-data e
5 × 2 crediti a The Odds API (1 credito per mercato × regione). I crediti
residui vengono letti dagli header e stampati nel riepilogo.

## Cosa il modello non fa

Stampato integralmente a ogni esecuzione, in sintesi:

- **Non conosce le notizie dell'ultimo minuto**: formazioni ufficiali,
  infortuni, squalifiche, turnover, motivazioni di classifica. Le formazioni
  escono circa un'ora prima del calcio d'inizio; eseguito prima, il modello
  ignora informazioni che il mercato ha già incorporato.
- **Un edge positivo non è un profitto garantito**: è la differenza fra due
  stime, entrambe incerte. L'intervallo mostrato copre solo l'errore di stima
  dei gol attesi, non l'errore di specificazione del modello. L'incertezza
  reale è più ampia di quella riportata.
- **Con pochi dati le stime sono fragili**: le righe con meno di
  `--min-matches` partite nello split casa/trasferta sono marcate `BASSA` o
  `INSUFF.` e restano visibili, mai escluse in silenzio.
- **Il mercato è un concorrente forte**: nei campionati principali le quote
  incorporano molte più informazioni di questo modello. Un edge sopra il 15%
  viene segnalato automaticamente come probabile problema di dati.

## Test

```bash
python3 edge_scan.py --self-test        # coerenza matematica + esempio di output
python3 -m tests.test_offline_pipeline  # pipeline completa su cache pre-caricata
```

Il self-test verifica fra l'altro che la griglia dei punteggi sommi a 1, che le
medie marginali coincidano con i λ, che il devig sia coerente nei tre metodi,
che le squadre con pochi dati siano tirate verso la media e marcate a bassa
affidabilità, e che l'output non contenga mai linguaggio da esito certo.
