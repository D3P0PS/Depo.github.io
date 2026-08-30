#!/bin/bash
"""Script che esegue l'analisi quotidiana, aggiorna la dashboard e invia notifiche."""

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
REPORTS_WEB="${SCRIPT_DIR}/reports_web"
PYTHON="${PYTHON:-python3}"

# Crea directory se necessaria
mkdir -p "$REPORT_DIR"
mkdir -p "$REPORTS_WEB"

# Carica variabili d'ambiente (se esiste .env)
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Logging
LOG_FILE="$SCRIPT_DIR/analysis_$(date +%Y-%m-%d).log"
exec 1> >(tee -a "$LOG_FILE")
exec 2>&1

echo "================================================"
echo "Edge Analysis - $(date +'%Y-%m-%d %H:%M:%S UTC')"
echo "================================================"

# Determina la data per il report
REPORT_DATE=$(date +%Y-%m-%d)
REPORT_FILE="$REPORT_DIR/report_${REPORT_DATE}.html"

# Se il report di oggi esiste già, saltalo
if [ -f "$REPORT_FILE" ]; then
    echo "⚠ Report per oggi già esistente: $REPORT_FILE"
else
    echo "🔄 Eseguo analisi edge..."
    cd "$SCRIPT_DIR"

    $PYTHON edge_scan.py \
        --odds-provider theoddsapi \
        --date today \
        --html "$REPORT_FILE" \
        --verbose

    if [ -f "$REPORT_FILE" ]; then
        echo "✓ Report generato: $REPORT_FILE"
    else
        echo "✗ Errore: report non generato"
        exit 1
    fi
fi

# Aggiorna dashboard
echo "🔄 Aggiorno dashboard..."
$PYTHON "$SCRIPT_DIR/dashboard.py" \
    --report-dir "$REPORT_DIR" \
    --output "$REPORTS_WEB/index.html"

# Copia tutti i report nella directory web
echo "📋 Copia report nella directory web..."
cp "$REPORT_DIR"/report_*.html "$REPORTS_WEB/" 2>/dev/null || true

echo "✓ Dashboard aggiornata: $REPORTS_WEB/index.html"

# Invia notifica Telegram (se configurato)
if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    echo "📲 Invia notifica Telegram..."
    $PYTHON "$SCRIPT_DIR/telegram_notify.py" \
        --report "$REPORT_FILE" \
        --bot-token "$TELEGRAM_BOT_TOKEN" \
        --chat-id "$TELEGRAM_CHAT_ID" \
        --limit 5 || echo "⚠ Notifica Telegram fallita (ma l'analisi è completa)"
else
    echo "⏭ Notifica Telegram non configurata"
fi

echo ""
echo "✓ Analisi completata!"
echo "📊 Dashboard: $REPORTS_WEB/index.html"
echo "📄 Report: $REPORT_FILE"
echo "================================================"
