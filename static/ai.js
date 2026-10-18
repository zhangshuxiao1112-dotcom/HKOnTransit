/**
 * HKOnTransit v2 — GenAI interpretation/explanation client.
 *
 * Progressive enhancement: if /api/ai/* is unreachable, the existing chip-based
 * preference UI keeps working untouched. GenAI never replaces the transport
 * engine — it only translates messy human language into structured inputs that
 * the existing routing/ETA/boarding flows act on.
 *
 * Same-origin API endpoints called (via fetch POST):
 *   GET  /api/ai/status               — active provider (mock | deepseek)
 *   POST /api/ai/interpret-preferences — { text } -> structured intent (preferences + chips)
 *   POST /api/ai/structure-report      — { text, context } -> mobility event (reserved hook)
 *   POST /api/ai/explain-route         — { route_data, preferences } -> explanation (reserved hook)
 *
 * The backend (server.py → ai/router.py) proxies these to the configured LLM
 * adapter. When the provider is "mock" (default), responses are deterministic
 * keyword-matched stubs and no network call leaves the server. When the
 * provider is "deepseek", the server calls the DeepSeek chat-completions API.
 *
 * To activate a live LLM, a maintainer must set these env vars on the server:
 *   HKONTRANSIT_AI_PROVIDER=deepseek
 *   DEEPSEEK_API_KEY=sk-...
 *   DEEPSEEK_MODEL=deepseek-chat        (optional, defaults to deepseek-chat)
 *   DEEPSEEK_BASE_URL=https://api.deepseek.com  (optional override)
 * See .env.example and ai/adapters/deepseek.py for details.
 *
 * Element ID contract (DOM elements this module binds to):
 *   apiStatus             — provider status badge appended beside it (top bar)
 *   nlPrefInput, nlPrefBtn — natural-language preference textarea + button
 *   aiIntentResult        — rendered AI interpretation results container
 *   prefFast, prefWalk, prefTransfer — existing UI chips auto-activated by AI
 *
 * Global hooks exposed for index.html inline code:
 *   window.__hkExplainRoute(routeData, preferences)   — reserved for results screen
 *   window.__hkStructureReport(text, context)          — reserved for report screen
 *
 * Maintainer notes:
 *   - This module degrades gracefully: any fetch failure shows a friendly
 *     message and the user can continue with the chip-based preference UI.
 *   - AI interpretation results are NEVER trusted outright — the backend
 *     runs Pydantic schema validation + transport-specific rule checks
 *     (see ai/validators.py) before the result reaches this client.
 *   - The module auto-runs on DOMContentLoaded (see bottom of file).
 */
(() => {
'use strict';
const $ = id => document.getElementById(id);

async function aiPost(url, body) {
  return window.hkRequest(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  });
}

/* ---- Provider status badge in the top bar ---- */
async function refreshAiStatus() {
  const el = $('apiStatus');
  if (!el) return;
  try {
    const s = await window.hkRequest('/api/ai/status');
    const label = s.provider === 'deepseek' ? (s.fallback_reason ? 'AI · Local fallback' : 'AI · DeepSeek configured') : 'AI · Local rule-based demo';
    // Leave the official-API status line intact; append an AI chip beside it.
    const aiChip = $('aiStatusChip') || (() => {
      const chip = document.createElement('span');
      chip.id = 'aiStatusChip';
      chip.className = 'badge grey optional';
      chip.style.marginLeft = '8px';
      el.parentElement.appendChild(chip);
      return chip;
    })();
    aiChip.textContent = `✦ ${label}`;
    aiChip.title = s.note || '';
  } catch { /* AI optional — fail silently, demo still works */ }
}

/* ---- Natural-language journey preference input ---- */
function renderInterpreted(intent) {
  const box = $('aiIntentResult');
  if (!box) return;
  box.replaceChildren();
  if (!intent.preferences || !intent.preferences.length) {
    box.append(mkNote('No clear preferences found. Try rephrasing or use the quick choices below.'));
    return;
  }
  const head = document.createElement('div');
  head.className = 'label';
  head.textContent = `AI interpreted (confidence ${(intent.confidence * 100) | 0}% · ${intent.language_detected})`;
  box.append(head);
  const wrap = document.createElement('div');
  wrap.className = 'ai-prefs';
  intent.preferences.forEach(p => {
    const row = document.createElement('div');
    row.className = 'ai-pref';
    const bar = document.createElement('span');
    bar.className = 'ai-bar';
    bar.style.setProperty('--w', (p.weight * 100) + '%');
    const label = document.createElement('span');
    label.className = 'ai-pref-label';
    label.textContent = humanPref(p.key);
    const w = document.createElement('small');
    w.textContent = p.weight >= 0.9 ? 'Required' : p.weight >= 0.5 ? 'Preferred' : 'Low priority';
    row.append(bar, label, w);
    wrap.append(row);
  });
  box.append(wrap);
  // Auto-activate the existing chips the AI suggested — keeps the transport
  // engine's deterministic preference path as the single source of truth.
  ['prefFast', 'prefWalk', 'prefTransfer'].forEach(id => {
    const chip = $(id);
    if (!chip) return;
    const on = (intent.suggested_chips || []).includes(id);
    chip.classList.toggle('active', on);
  });
  if (intent.notes) {
    const n = document.createElement('div');
    n.className = 'smallprint';
    n.textContent = intent.notes;
    box.append(n);
  }
}

function humanPref(key) {
  return ({
    faster: 'Faster', fewer_transfers: 'Fewer transfers', less_walking: 'Less walking',
    cheaper: 'Lower cost', accessible: 'Accessible travel', less_crowded: 'Less crowded',
    scenic: 'Scenic', reliable: 'Reliable',
  })[key] || key;
}

function mkNote(text) {
  const d = document.createElement('div');
  d.className = 'note';
  d.textContent = text;
  return d;
}

function bindNlInput() {
  const input = $('nlPrefInput');
  const btn = $('nlPrefBtn');
  if (!input || !btn) return;
  async function run() {
    const text = (input.value || '').trim();
    if (!text) { window.__hk_notify?.('Describe your travel needs first.'); return; }
    const box = $('aiIntentResult');
    box?.replaceChildren(mkNote('AI Interpreting your needs…'));
    btn.disabled = true;
    try {
      const intent = await aiPost('/api/ai/interpret-preferences', { text });
      renderInterpreted(intent);
      window.__hk_notify?.(intent.preferences?.length
        ? `Detected ${intent.preferences.length}  preferences and updated the quick choices.`
        : 'No clear preferences found. Try again or use the quick choices.');
    } catch (e) {
      box?.replaceChildren(mkNote('AI interpretation unavailable: ' + e.message + '. You can still use the quick choices below.'));
    } finally {
      btn.disabled = false;
    }
  }
  btn.addEventListener('click', run);
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); run(); } });
}

/* ---- (Reserved) route explanation hook ----
 * When the results screen gains a real route payload, call this to show a
 * passenger-friendly explanation instead of raw numbers. Stubbed for now so
 * the integration point is visible and the contract is fixed. */
window.__hkExplainRoute = async function (routeData, preferences) {
  try {
    return await aiPost('/api/ai/explain-route', { route_data: routeData, preferences });
  } catch (e) {
    return { route_summary: '', trade_offs: [], _error: e.message };
  }
};

/* ---- (Reserved) community report structuring hook ----
 * Pre-fills the report form's structured fields from free text, but the
 * verification_status stays 'unverified' — the deterministic workflow owns it. */
window.__hkStructureReport = async function (text, context) {
  try {
    return await aiPost('/api/ai/structure-report', { text, context });
  } catch (e) {
    return { _error: e.message };
  }
};

document.addEventListener('DOMContentLoaded', () => {
  refreshAiStatus();
  bindNlInput();
});
})();
