let strategyChart = {};
let currentProfileKey = '';

function profileKey({ decks, s17, das, surrender }) {
  return `${decks}D_${s17}_${das === 'true' ? 'DAS' : 'NDAS'}_${surrender.toUpperCase()}`;
}

async function loadChart() {
  const decks = document.getElementById('decks').value;
  const s17 = document.getElementById('s17').value;
  const das = document.getElementById('das').value;
  const surrender = document.getElementById('surrender').value;

  currentProfileKey = profileKey({ decks, s17, das, surrender });

  let chartPath = '/charts/sample-8d-h17-das-nosurr.json';
  if (!(decks === '8' && s17 === 'H17' && das === 'true' && surrender === 'none')) {
    alert('Sample includes only 8D H17 DAS no-surrender; add full charts for other rules.');
  }

  const res = await fetch(chartPath);
  strategyChart = await res.json();

  document.getElementById('edgePreview').textContent =
    'Loaded strategy; preview the house edge with a rules calculator before committing to this table.';
}

function normalize(val) {
  const n = Number(val);
  if (Number.isNaN(n) || n < 2 || n > 11) return null;
  return n;
}

function decide() {
  const handType = document.getElementById('handType').value;
  const playerVal = document.getElementById('playerVal').value.trim().toUpperCase();
  const dealerUp = normalize(document.getElementById('dealerUp').value);
  if (!dealerUp) {
    document.getElementById('action').textContent = 'Enter dealer up-card 2-11 (11=Ace).';
    return;
  }

  let key = '';
  if (handType === 'pair') key = `P_${playerVal}`;
  else if (handType === 'soft') key = `S_${playerVal}`;
  else key = `H_${playerVal}`;

  const row = strategyChart[key];
  const action = row ? row[String(dealerUp)] : null;
  document.getElementById('action').textContent = action ? `Action: ${action}` : 'No entry for this combination; ensure chart coverage.';
}

// Session tracking
const SESSION_KEY = 'bj_session';
function startSession() {
  const s = {
    startedAt: new Date().toISOString(),
    bankrollStart: Number(document.getElementById('bankrollStart').value || 0),
    stopLoss: Number(document.getElementById('stopLoss').value || 0),
    winCap: Number(document.getElementById('winCap').value || 0),
    entries: []
  };
  localStorage.setItem(SESSION_KEY, JSON.stringify(s));
  renderSession();
}
function logRound() {
  const s = JSON.parse(localStorage.getItem(SESSION_KEY) || '{}');
  if (!s.entries) return;
  const stake = Number(document.getElementById('stake').value || 0);
  const result = document.getElementById('result').value;
  s.entries.push({ time: new Date().toISOString(), profile: currentProfileKey, stake, result });
  localStorage.setItem(SESSION_KEY, JSON.stringify(s));
  renderSession();
}
function renderSession() {
  const s = JSON.parse(localStorage.getItem(SESSION_KEY) || '{}');
  const div = document.getElementById('sessionStatus');
  const log = document.getElementById('sessionLog');
  if (!s.entries) { div.textContent = 'No active session.'; log.textContent = ''; return; }
  const net = s.entries.reduce((acc, e) => e.result === 'win' ? acc + e.stake : e.result === 'loss' ? acc - e.stake : acc, 0);
  div.textContent = `Started: ${new Date(s.startedAt).toLocaleString()} | Net: ${net}`;
  log.innerHTML = s.entries.slice(-20).map((e) => `${new Date(e.time).toLocaleTimeString()} | ${e.profile} | ${e.stake} | ${e.result}`).join('<br/>');
}

// Side bet warning
function sideBetToggle() {
  const enabled = document.getElementById('enableSideBets').checked;
  const warn = document.getElementById('sideBetWarning');
  warn.textContent = enabled ? 'Warning: Side bets often have a substantially higher house edge than the main game.' : 'Side bets disabled.';
}

// Install prompt
let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  document.getElementById('installBtn').hidden = false;
});
document.getElementById('installBtn').addEventListener('click', async () => {
  if (deferredPrompt) {
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    document.getElementById('installBtn').hidden = true;
  }
});

// Events and SW registration
document.getElementById('loadChartBtn').addEventListener('click', loadChart);
document.getElementById('decideBtn').addEventListener('click', decide);
document.getElementById('startSessionBtn').addEventListener('click', startSession);
document.getElementById('logRoundBtn').addEventListener('click', logRound);
document.getElementById('enableSideBets').addEventListener('change', sideBetToggle);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js');
renderSession();
