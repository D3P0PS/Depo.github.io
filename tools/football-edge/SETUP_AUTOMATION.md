# 🤖 Setup Automazione — Dashboard + Notifiche Telegram

Guida per configurare l'automazione quotidiana dell'edge analysis con dashboard web e notifiche Telegram.

---

## 📋 Cosa faremo

1. **Cron job** esegue ogni giorno l'analisi
2. **Dashboard web** mostra ultimi N giorni di report
3. **Notifiche Telegram** con top 5 edge opportunities

---

## 🔧 Setup (5 minuti)

### 1. Rendi eseguibile lo script

```bash
cd /path/to/football-edge
chmod +x run_daily.sh
```

### 2. Configura Telegram (opzionale ma consigliato)

Se vuoi notifiche Telegram:

**a) Crea un bot Telegram:**
- Apri Telegram, cerca `@BotFather`
- Digita `/start`, poi `/newbot`
- Segui le istruzioni, riceverai: `123456:ABCDEfgh...` (token)

**b) Ottieni il tuo chat ID:**
- Cerca `@userinfobot` su Telegram
- Digita `/start`
- Riceverai il tuo ID (es: `987654321`)

**c) Configura le variabili d'ambiente:**

```bash
# Aggiungi al file .env nella cartella dello script:
cat >> .env <<EOF
TELEGRAM_BOT_TOKEN=123456:ABCDEfgh...
TELEGRAM_CHAT_ID=987654321
EOF
```

### 3. Configura il cron job

**Per esecuzione quotidiana alle 06:00 UTC** (prima del kickoff europeo):

```bash
# Apri crontab
crontab -e

# Aggiungi questa riga (sostituisci il path):
0 6 * * * cd /path/to/football-edge && bash run_daily.sh >> /tmp/edge_analysis.log 2>&1
```

**Opzioni di timing:**
- `0 6 * * *` = ogni giorno alle 06:00 UTC (mattina)
- `0 10,18 * * *` = due volte al giorno (mattina + sera)
- `0 * * * *` = ogni ora
- `*/30 * * * *` = ogni 30 minuti

### 4. Servire la dashboard via HTTP

**Opzione A: Python http.server (semplice)**

```bash
cd /path/to/football-edge/reports_web
python3 -m http.server 8080 &
```

Accedi: `http://localhost:8080` o `http://vps-ip:8080`

**Opzione B: Nginx (production)**

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        root /path/to/football-edge/reports_web;
        index index.html;
    }
}
```

---

## 🧪 Test prima di attivare

### Esegui il setup manualmente una volta:

```bash
cd /path/to/football-edge
bash run_daily.sh
```

Dovresti vedere:
- ✓ Analisi completata
- ✓ Dashboard aggiornata
- ✓ Notifica Telegram inviata (se configurata)

### Test solo notifica:

```bash
python3 telegram_notify.py \
    --report reports/report_2026-08-30.html \
    --bot-token YOUR_TOKEN \
    --chat-id YOUR_ID \
    --test
```

---

## 📁 Struttura directory

```
football-edge/
├── edge_scan.py
├── run_daily.sh           # Script di automazione
├── dashboard.py           # Genera dashboard
├── telegram_notify.py     # Notifiche Telegram
├── .env                   # Credenziali (gitignore)
├── reports/               # Report HTML giornalieri
│   ├── report_2026-08-28.html
│   ├── report_2026-08-29.html
│   └── report_2026-08-30.html
└── reports_web/           # Copia per web server
    ├── index.html         # Dashboard
    └── report_*.html
```

---

## 📊 Cosa vedrai

### Dashboard (`reports_web/index.html`)

- Lista dei report ultimi 30 giorni
- Summary per ogni giorno (righe con quota, top edge, stato calibrazione)
- Link diretti ai report completi
- Auto-refresh

### Notifica Telegram

```
📊 Edge Analysis — 2026-08-30

🎯 Top Opportunities

1. Chelsea - Brighton Hove
   Market: 1X2 (2 (trasferta))
   Edge: +206.3%

2. Manchester City - Fulham
   Market: Over/Under 2.5 (Over 2.5)
   Edge: +68.6%

...

📄 Report completo: [Apri]

_Ricorda: queste sono stime statistiche, non pronostici._
```

---

## 🔍 Troubleshooting

### Cron non esegue

```bash
# Verifica che cron sia attivo
sudo service cron status

# Vedi i log
sudo tail -f /var/log/syslog | grep CRON
```

### Dashboard vuota

```bash
# Verifica directory
ls -la reports/
ls -la reports_web/

# Esegui manualmente
python3 dashboard.py --report-dir reports/ --output reports_web/index.html
```

### Notifica Telegram non arriva

```bash
# Test con --test flag
python3 telegram_notify.py \
    --report reports/report_2026-08-30.html \
    --test

# Verifica token/chat_id
echo $TELEGRAM_BOT_TOKEN
echo $TELEGRAM_CHAT_ID
```

---

## 📝 Log

I log di ogni esecuzione vengono salvati in:
```
analysis_YYYY-MM-DD.log
```

Controlla gli errori:
```bash
tail -f analysis_*.log
```

---

## 🚀 Prossimi step

1. ✅ Test manuale con `bash run_daily.sh`
2. ✅ Configura Telegram (opzionale)
3. ✅ Aggiungi cron job
4. ✅ Accedi alla dashboard da browser

Fatto! L'analisi funzionerà autonomamente 🎯
