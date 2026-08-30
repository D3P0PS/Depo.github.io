# 🎯 Best Practices per Edge Analysis

Suggerimenti pratici per ottenere risultati affidabili dalla tua analisi edge.

---

## 1️⃣ **Riduci l'eccesso di fiducia con `--market-blend 0.3`**

### Il Problema
Il modello Poisson bivariato tende ad essere troppo sicuro di se stesso, specialmente quando:
- Il campionato ha regolarità storica prevedibile
- Le squadre sono ben separate per qualità
- I dati storici sono limitati

Questo produce edge illusori: il modello stima +20% quando la realtà è +5%.

### La Soluzione
```bash
--market-blend 0.3  # Di default, già incluso
```

**Cosa fa:**
- Mescola il 30% della probabilità del mercato con il 70% del modello
- Riduce edge molto alti (> 15%) in modo naturale
- Mantiene segnali veri ma li rende più conservatori

**Quando aumentare:**
- `--market-blend 0.5` se il report è ancora sospetto (> 30% edge > 15%)
- All'inizio della stagione quando i dati sono pochi

---

## 2️⃣ **Escludi le righe INSUFF. con `--skip-insufficient`**

### Il Problema
Le righe marcate **INSUFF.** hanno meno di 3 partite in uno dei due split (casa/trasferta):
```
[INSUFF.] Napoli vs Como 1907: Napoli non ha partite in trasferta nel periodo...
```

Queste sono probabilmente stime sbagliate:
- Squadra appena promossa
- Cambio di allenatore
- Infortunio di un titolare

### La Soluzione
```bash
--skip-insufficient  # Nuova opzione
```

**Cosa fa:**
- Esclude completamente le righe INSUFF. dal report
- Le mantiene nei file CSV/JSON (comunque disponibili)
- Riduce il rumore, mostra solo ciò che ha abbastanza dati

**Quando usarla:**
- Di default, per report puliti
- Sempre all'inizio della stagione

---

## 3️⃣ **Allarga la finestra di forma a inizio stagione**

### Il Problema
L'inizio stagione ha pochi dati storici:
- Default: `--form-matches 10` (ultimi 10 match)
- Ma le squadre hanno giocato solo 3-4 partite

Il modello ha "la vista corta", pesa troppo gli ultimi risultati.

### La Soluzione
```bash
# All'inizio della stagione (primi 6 match):
--form-matches 5 --half-life 30
```

**Parametri:**
- `--form-matches 5` — usa ultimi 5 match (non 10)
- `--half-life 30` — mezza vita 30 giorni (non 60) → pesa più la storia

**Timeline stagione:**
| Periodo | Consiglio |
|---------|-----------|
| Match 1-3 | `--form-matches 5 --half-life 30` |
| Match 4-10 | `--form-matches 7 --half-life 45` |
| Match 11+ | Default: `--form-matches 10 --half-life 60` |

### Avvertenza Automatica
Il tool rileva automaticamente se > 30% delle righe ha pochi dati e mostra un banner:

```
⚠ Stagione appena iniziata — dati storici limitati

Il 45% righe ha meno di 3 partite per split casa/trasferta.
Suggerisco: --form-matches 5 --half-life 30
```

---

## 📋 Checklist per una buona analisi

### Setup Iniziale
- [ ] Chiavi API configurate (`.env`)
- [ ] `--market-blend 0.3` è il default ✓
- [ ] Dashboard e notifiche Telegram configurate ✓

### Ogni Analisi
- [ ] Usa `--skip-insufficient` se il report ha troppo rumore
- [ ] Leggi l'avvertenza di calibrazione (top del report)
- [ ] Se "stagione appena iniziata": aggiusta parametri come suggerito

### Interpretazione Risultati

| Scenario | Azione |
|----------|--------|
| Edge > 20% | Probabilmente illusorio. Verifica il match manualmente |
| 30-50% INSUFF. | Usa `--skip-insufficient` o aumenta `--market-blend` |
| Calibrazione "sospetta" | Aumenta `--market-blend` (+0.1) finché non sparisce |
| Inizio stagione | Usa form-matches/half-life ridotti |

---

## 🔧 Comandi Tipici

### Analisi conservativa (preferita)
```bash
python3 edge_scan.py \
  --odds-provider theoddsapi \
  --date today \
  --market-blend 0.3 \
  --skip-insufficient \
  --html report.html
```

### Inizio stagione
```bash
python3 edge_scan.py \
  --odds-provider theoddsapi \
  --date today \
  --form-matches 5 \
  --half-life 30 \
  --market-blend 0.4 \
  --skip-insufficient \
  --html report.html
```

### Esplorazione (meno filtri)
```bash
python3 edge_scan.py \
  --odds-provider theoddsapi \
  --date today \
  --market-blend 0.2 \
  --html report.html
```

---

## ⚠️ Errori Comuni

### ❌ "Il mio report ha 90% edge > 15%"
**Causa:** `--market-blend` troppo basso (o default 0.0 da versioni vecchie)
**Fix:** Usa `--market-blend 0.5` oppure escludere quelle righe con `--min-edge 5`

### ❌ "Tutte le righe dicono INSUFF."
**Causa:** Campionato troppo nuovo oppure squadra in una categoria strana
**Fix:** Aspetta 10+ match della stagione, oppure aumenta `--form-matches`

### ❌ "Ieri aveva 50 edge, oggi 5"
**Causa:** Probabilmente normale. Il mercato e il modello si aggiornano man mano
**Fix:** Non è un errore. L'edge riflette il consensus del mercato.

---

## 📊 Metriche di Sanità Mentale

Ogni report dovrebbe avere:

✓ **Righe con quota:** > 10 (almeno qualche opportunità)
✓ **Calibrazione:** Non sospetta (media scostamento < 8 punti)
✓ **Edge max:** < 50% (se > 50%, probabilmente un errore)
✓ **% INSUFF.:** < 20% (se > 20%, i dati sono troppo pochi)

Se una metrica è fuori range → aumenta `--market-blend` oppure `--skip-insufficient`.

---

## 🔗 Risorse

- [README principale](README.md)
- [Setup Automazione](SETUP_AUTOMATION.md)
- Fonte quote: The Odds API (`--odds-provider theoddsapi`)
- Dati storici: football-data.org (richiede API key)
