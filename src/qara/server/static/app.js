"use strict";

const DEFAULT_PROJECT = window._ARI_DEFAULT_PROJECT ?? "";

// ── State ──
let currentProject = DEFAULT_PROJECT || "";

// ── Utilities ──
function el(id) { return document.getElementById(id); }
function fmt(n) { return n == null ? "—" : n.toLocaleString(); }
function fmtMs(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return ms + "ms";
  if (ms < 60000) return (ms/1000).toFixed(1) + "s";
  return Math.floor(ms/60000) + "m " + ((ms%60000)/1000).toFixed(0) + "s";
}
function fmtDate(ts) {
  if (ts == null) return "—";
  return new Date(ts * 1000).toLocaleString();
}
function badge(cls, text) {
  return `<span class="badge badge-${cls}">${text}</span>`;
}
function pct(p) {
  if (p == null) return "—";
  return (p * 100).toFixed(0) + "%";
}
function truncate(s, n) {
  if (!s) return "—";
  return s.length > n ? s.slice(0, n) + "…" : s;
}
function sparkHtml(chars) {
  if (!chars) return "—";
  return chars.split("").map(c => {
    if (c === "✓" || c === "P") return `<span style="color:var(--pass)">✓</span>`;
    if (c === "✗" || c === "F") return `<span style="color:var(--fail)">✗</span>`;
    return `<span style="color:var(--muted)">–</span>`;
  }).join("");
}

function _sparkGrid(sparkline) {
  if (!sparkline) return '<span style="color:var(--muted)">—</span>';
  return '<div class="spark-grid">' +
    sparkline.split("").map(c => {
      const bg = (c === "✓" || c === "P") ? "var(--pass)" :
                 (c === "✗" || c === "F") ? "var(--fail)" : "var(--border)";
      return `<span class="spark-sq" style="background:${bg}"></span>`;
    }).join("") + "</div>";
}

function _sparklineTrendCell(sparkline) {
  const stable = (tip = "") =>
    `<span class="trend-stable" onmouseenter="_trendTip(event,this)" onmouseleave="_hmHide()"
      data-tip="${escHtml(tip || "Stable — less than 5pp change across the run window")}">&#8212;</span>`;

  if (!sparkline) return stable("Not enough history to compute a trend.");
  const chars = sparkline.split("").filter(c => c === "P" || c === "✓" || c === "F" || c === "✗");
  if (chars.length < 4) return stable("Not enough runs to compute a trend (need at least 4).");

  const pass = c => c === "P" || c === "✓";
  const half  = Math.floor(chars.length / 2);
  const r0    = chars.slice(0, half).filter(pass).length / half;
  const r1    = chars.slice(-half).filter(pass).length / half;
  const delta = Math.round((r1 - r0) * 100);
  const r0pct = Math.round(r0 * 100);
  const r1pct = Math.round(r1 * 100);

  if (Math.abs(delta) < 5)
    return stable(`Stable — pass rate barely moved (${r0pct}% → ${r1pct}%) across the run window.`);

  if (delta > 0) {
    const tip = `Improving — pass rate rose from ${r0pct}% (earlier runs) to ${r1pct}% (recent runs), a +${delta}% gain.`;
    return `<span class="trend-up" onmouseenter="_trendTip(event,this)" onmouseleave="_hmHide()"
      data-tip="${escHtml(tip)}">&#8599; +${delta}%</span>`;
  }
  const tip = `Declining — pass rate dropped from ${r0pct}% (earlier runs) to ${r1pct}% (recent runs), a ${delta}% fall.`;
  return `<span class="trend-down" onmouseenter="_trendTip(event,this)" onmouseleave="_hmHide()"
    data-tip="${escHtml(tip)}">&#8600; ${delta}%</span>`;
}

function _heatmapHistory(sparkline) {
  if (!sparkline) return '<span style="color:var(--muted)">—</span>';
  const squares = sparkline.split("").map((c, i) => {
    const pass = c === "✓" || c === "P";
    const fail = c === "✗" || c === "F";
    const cls  = pass ? "hm-sq pass" : fail ? "hm-sq fail" : "hm-sq skip";
    const label = pass ? "Passed" : fail ? "Failed" : "Skipped";
    return `<span class="${cls}" data-n="${i + 1}" data-label="${label}"
      onmouseenter="_hmTip(event,this)" onmouseleave="_hmHide()"></span>`;
  }).join("");
  return `<div class="hm-grid">${squares}</div>`;
}

function _hmTip(e, sq) {
  const tip = document.getElementById("ari-tooltip");
  if (!tip) return;
  const label = sq.dataset.label;
  const color = label === "Passed" ? "var(--pass)" : label === "Failed" ? "var(--fail)" : "var(--muted)";
  tip.innerHTML = `<span style="color:${color};font-weight:600">${label}</span> · Run #${sq.dataset.n}`;
  tip.style.left = (e.clientX + 12) + "px";
  tip.style.top  = (e.clientY - 36) + "px";
  tip.style.opacity = "1";
}

function _hmHide() {
  const tip = document.getElementById("ari-tooltip");
  if (tip) tip.style.opacity = "0";
}

function _trendTip(e, span) {
  const tip = document.getElementById("ari-tooltip");
  if (!tip) return;
  tip.textContent = span.dataset.tip;
  tip.style.left = (e.clientX + 14) + "px";
  tip.style.top  = (e.clientY - 40) + "px";
  tip.style.opacity = "1";
}

function _stabilityRing(passRate, flipScore) {
  const pct = Math.round((passRate ?? 0) * 100);
  const r = 14, sw = 3.5, sz = (r + sw) * 2;
  const circ = 2 * Math.PI * r;
  const arc  = circ * pct / 100;
  const color = pct >= 70 ? "var(--pass)" : pct >= 40 ? "var(--flaky)" : "var(--fail)";
  return `<div class="stability-cell">
    <svg width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}" style="transform:rotate(-90deg);flex-shrink:0">
      <circle cx="${sz/2}" cy="${sz/2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="${sw}"/>
      <circle cx="${sz/2}" cy="${sz/2}" r="${r}" fill="none" stroke="${color}" stroke-width="${sw}"
              stroke-linecap="round" stroke-dasharray="${arc.toFixed(2)} ${(circ-arc).toFixed(2)}"/>
    </svg>
    <div class="stability-text">
      <span class="stability-pct" style="color:${color}">${pct}%</span>
      ${flipScore != null ? `<span class="stability-sub">${flipScore.toFixed(2)}</span>` : ""}
    </div>
  </div>`;
}

// ── Resizable table columns ──
function _makeTableResizable(tableId) {
  const table = el(tableId);
  if (!table || table.querySelector('.col-resizer')) return; // already done
  const ths = Array.from(table.querySelectorAll('thead th'));
  // Lock in natural widths before switching to fixed layout
  ths.forEach(th => { th.style.width = th.offsetWidth + 'px'; });
  table.style.tableLayout = 'fixed';
  ths.forEach(th => {
    const handle = document.createElement('div');
    handle.className = 'col-resizer';
    th.appendChild(handle);
    handle.addEventListener('mousedown', e => {
      const startX = e.pageX;
      const startW = th.offsetWidth;
      e.preventDefault();
      handle.classList.add('dragging');
      const onMove = e => { th.style.width = Math.max(40, startW + (e.pageX - startX)) + 'px'; };
      const onUp   = () => {
        handle.classList.remove('dragging');
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup',   onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup',   onUp);
    });
  });
}

// ── On-page debug logger ──
(function() {
  const _logEl = () => el("debug-log");
  const _toggleBtn = () => el("debug-toggle");
  const _lines = [];

  function _ts() {
    const d = new Date();
    return d.toTimeString().slice(0,8) + "." + String(d.getMilliseconds()).padStart(3,"0");
  }

  window.ariLog = function(level, msg) {
    const line = _ts() + "  " + msg;
    _lines.push(line);
    const native = level === "error" ? console.error : level === "warn" ? console.warn : console.log;
    native("[ARI]", msg);
    const logEl = _logEl();
    if (logEl) {
      const div = document.createElement("div");
      div.className = "dl dl-" + (level === "error" ? "error" : level === "warn" ? "warn" : level === "ok" ? "ok" : "info");
      div.innerHTML = `<span class="dl-ts">${_ts()}</span>${escHtml(msg)}`;
      logEl.appendChild(div);
      logEl.scrollTop = logEl.scrollHeight;
    }
    if (level === "error") {
      const btn = _toggleBtn();
      if (btn) btn.classList.add("has-error");
    }
  };

  // Intercept unhandled JS errors and show them in the panel
  window.addEventListener("error", function(e) {
    window.ariLog("error", "JS error: " + e.message + " (" + e.filename + ":" + e.lineno + ")");
  });
  window.addEventListener("unhandledrejection", function(e) {
    window.ariLog("error", "Unhandled promise rejection: " + (e.reason && e.reason.message ? e.reason.message : String(e.reason)));
  });

  // Wire up toggle button and controls (after DOM ready)
  document.addEventListener("DOMContentLoaded", function() {
    const btn = el("debug-toggle");
    const panel = el("debug-panel");
    if (btn && panel) {
      btn.addEventListener("click", function() {
        panel.classList.toggle("open");
        btn.classList.remove("has-error");
      });
    }
    const clearBtn = el("debug-clear");
    if (clearBtn) clearBtn.addEventListener("click", function() {
      const log = _logEl();
      if (log) log.innerHTML = "";
      _lines.length = 0;
    });
    const copyBtn = el("debug-copy");
    if (copyBtn) copyBtn.addEventListener("click", function() {
      navigator.clipboard.writeText(_lines.join("\\n")).then(function() {
        copyBtn.textContent = "✓ Copied";
        setTimeout(function(){ copyBtn.textContent = "\U0001f4cb Copy"; }, 1500);
      });
    });
  });
})();

// ── Status bar ──
function showStatus(level, msg, retryFn) {
  const bar = el("status-bar");
  if (!bar) return;
  let html = `<span class="sb-msg">${escHtml(msg)}</span>`;
  if (retryFn) html += `<button class="sb-retry" id="sb-retry-btn">Retry</button>`;
  html += `<button class="sb-dismiss" title="Dismiss">&times;</button>`;
  bar.className = level;  // "error", "warn", "info"
  bar.innerHTML = html;
  bar.classList.remove("hidden");
  bar.querySelector(".sb-dismiss").addEventListener("click", () => bar.classList.add("hidden"));
  if (retryFn) bar.querySelector("#sb-retry-btn").addEventListener("click", () => { bar.classList.add("hidden"); retryFn(); });
}
function clearStatus() {
  const bar = el("status-bar");
  if (bar) bar.classList.add("hidden");
}

async function apiFetch(path, { timeoutMs = 15000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(path, { signal: ctrl.signal });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    return await res.json();
  } catch(e) {
    if (e.name === "AbortError") throw new Error(`Request timed out after ${timeoutMs/1000}s: ${path}`);
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// ── Project selector ──
async function loadProjects() {
  const sel = el("project-select");
  sel.innerHTML = `<option value="">Loading projects…</option>`;
  ariLog("info", "Fetching /api/projects…");
  try {
    const projects = await apiFetch("/api/projects");
    ariLog("ok", `Projects loaded: [${projects.join(", ") || "(none)"}]`);
    clearStatus();
    sel.innerHTML = `<option value="">All Projects</option>` +
      projects.map(p => `<option value="${p}"${p === currentProject ? " selected" : ""}>${p}</option>`).join("");
    if (!currentProject && projects.length === 1) {
      currentProject = projects[0];
      sel.value = currentProject;
    }
    if (projects.length === 0) {
      showStatus("warn", "⚠️ No projects found. Have you ingested any test reports? Run: ari ingest <report-path>");
      ariLog("warn", "No projects in DB. Ingest a report first.");
    }
    loadAll();
  } catch(e) {
    ariLog("error", `Failed to load projects: ${e.message}`);
    const isTimeout = e.message.includes("timed out");
    const hint = isTimeout
      ? "Server did not respond in time. Is 'ari serve' running?"
      : `Could not reach the ARI server: ${e.message}`;
    sel.innerHTML = `<option value="">❌ Error loading projects</option>`;
    showStatus("error", `❌ ${hint}`, loadProjects);
    // Auto-retry once after 5 s
    ariLog("warn", "Will auto-retry in 5s…");
    setTimeout(() => {
      ariLog("info", "Auto-retrying loadProjects…");
      loadProjects();
    }, 5000);
  }
}

el("project-select").addEventListener("change", e => {
  currentProject = e.target.value;
  loadAll();
});

function loadAll() {
  loadRuns();
  loadAnalysis();
  loadHomepageCards();
  loadRisk();
  loadLLMInfo();

  // Reset Incidents: clear the pinned run ID so the first run of the new
  // project is auto-selected when the Incidents tab is (re-)visited.
  _incidentsRunId = null;
  if (document.querySelector("#panel-incidents.active")) {
    loadIncidents();
  }

  // Reset Analysis filter state so the filter rows are re-initialised for
  // the new project (otherwise stale owner/suite options persist).
  _filterInitialised = false;

  // Clear chat history — messages from the previous project must not leak.
  const chatMsgs = el("chat-messages");
  const chatWelcome = el("chat-welcome");
  if (chatMsgs) chatMsgs.innerHTML = "";
  if (chatWelcome) chatWelcome.style.display = "";
  if (chatMsgs) chatMsgs.style.display = "none";

  // Reset comparison when project changes so stale data isn't shown.
  _cmp.result = null;
  _cmp.oldestRunId = null;
  el("cmp-matrix-wrap").style.display = "none";
  el("cmp-info").textContent = "Select a run window to begin comparison.";
  el("cmp-info").style.display = "";
  el("cmp-summary-cards").innerHTML = "";
  // Re-activate the currently active preset button for UX consistency
  const activePreset = document.querySelector(".cmp-preset.active");
  if (activePreset && document.querySelector("#panel-compare.active")) {
    activePreset.click();
  }
};

// ── Tab navigation ──
function switchTab(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
  const tab = document.querySelector(`[data-tab="${name}"]`);
  if (tab) tab.classList.add("active");
  const panel = el("panel-" + name);
  if (panel) panel.classList.add("active");
  if (name === "analysis") loadAnalysis();
  if (name === "risk") loadRisk();
  if (name === "incidents") loadIncidents();
  if (name === "compare" && !_cmp.result) cmpLoadWindow(5);
  history.replaceState(null, "", "/?tab=" + encodeURIComponent(name));
}
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", e => {
    // Normal click: switch in-page. Ctrl/Meta/middle-click: let browser open new tab.
    if (!e.ctrlKey && !e.metaKey && e.button !== 1) {
      e.preventDefault();
      switchTab(tab.dataset.tab);
    }
  });
});

// ── Runs panel ──
let _runsData = [];
let _runsPage = 0;
let _runsPageSize = 25;

function _renderRunsPage() {
  const body = el("runs-body");
  const pagination = el("runs-pagination");
  const pageInfo = el("runs-page-info");
  const prevBtn = el("runs-prev");
  const nextBtn = el("runs-next");

  const total = _runsData.length;
  const totalPages = Math.ceil(total / _runsPageSize);
  const start = _runsPage * _runsPageSize;
  const end = Math.min(start + _runsPageSize, total);
  const pageSlice = _runsData.slice(start, end);

  body.innerHTML = pageSlice.map(r => {
    const passPct = (r.total_tests > 0) ? Math.round(r.passed_count / r.total_tests * 100) : null;
    const pctColor = passPct === null ? "var(--muted)" : passPct >= 90 ? "var(--pass)" : passPct >= 60 ? "#f59e0b" : "var(--fail)";
    const pctLabel = passPct === null ? "—" : passPct + "%";
    return `<tr class="run-row" data-run-id="${r.run_id}" data-run-seq="${r.run_sequence ?? ""}">
      <td class="mono">${r.run_sequence ?? "—"}</td>
      <td>${escHtml(r.project ?? "—")}</td>
      <td>${escHtml(r.report_format)}</td>
      <td style="white-space:nowrap">${fmtDate(r.started_at)}</td>
      <td style="white-space:nowrap">${fmtMs(r.total_ms)}</td>
      <td>${fmt(r.total_tests)}</td>
      <td style="color:var(--pass)">${fmt(r.passed_count)}</td>
      <td style="color:var(--fail)">${fmt(r.failed_count)}</td>
      <td style="color:var(--skip)">${fmt(r.skipped_count)}</td>
      <td style="color:${pctColor};font-weight:600">${pctLabel}</td>
      <td class="mono" style="font-size:12px">${escHtml(r.branch ?? "—")}</td>
      <td class="mono" style="font-size:12px">${escHtml(r.build_number ?? "—")}</td>
    </tr>`;
  }).join("");

  if (total > _runsPageSize) {
    pagination.style.display = "flex";
    pageInfo.textContent = `${start + 1}–${end} of ${total}`;
    prevBtn.disabled = _runsPage === 0;
    nextBtn.disabled = _runsPage >= totalPages - 1;
  } else {
    pagination.style.display = "none";
  }
  _makeTableResizable("runs-table");
}

async function loadLLMInfo() {
  try {
    const data = await fetch("/api/llm/info").then(r => r.json());
    const label = el("llm-model-label");
    if (label && data.model) {
      label.textContent = data.model;
      label.title = `Provider: ${data.provider}`;
    }
  } catch (_) {
    // silently ignore — the fallback text "your local LLM" stays in place
  }
}

async function loadRuns() {
  const body = el("runs-body");
  const statsRow = el("runs-stats");
  const pagination = el("runs-pagination");
body.innerHTML = `<tr><td colspan="12" class="loading">Loading runs…</td></tr>`;
  statsRow.innerHTML = "";
  pagination.style.display = "none";
  ariLog("info", `Fetching runs (project=${currentProject || "(all)"})`);
  try {
    const qs = currentProject ? `?project=${encodeURIComponent(currentProject)}&limit=500` : "?limit=500";
    const runs = await apiFetch("/api/runs" + qs);
    ariLog("ok", `${runs.length} run(s) loaded.`);
    _runsData = runs;
    _runsPage = 0;

    // Stats
    statsRow.innerHTML = `
      <div class="stat-card"><div class="label">Total Runs</div><div class="value">${fmt(runs.length)}</div></div>
      <div class="stat-card"><div class="label">Projects</div><div class="value">${fmt([...new Set(runs.map(r=>r.project).filter(Boolean))].length)}</div></div>
      <div class="stat-card"><div class="label">Latest</div><div class="value" style="font-size:16px">${runs.length ? fmtDate(runs[0].started_at) : "—"}</div></div>
    `;

    if (!runs.length) {
      body.innerHTML = `<tr><td colspan="12" class="empty">No runs found.</td></tr>`;
      return;
    }

    _renderRunsPage();
  } catch(e) {
    ariLog("error", `Failed to load runs: ${e.message}`);
    body.innerHTML = `<tr><td colspan="12" class="error-msg">❌ Failed to load runs: ${escHtml(e.message)} — <a href="javascript:loadRuns()" style="color:var(--accent)">Retry</a></td></tr>`;
  }
}

// Pagination controls wire-up (runs once after DOM ready)
(function wirePagination() {
  const prevBtn = el("runs-prev");
  const nextBtn = el("runs-next");
  const pageSizeSel = el("runs-page-size");
  if (prevBtn) prevBtn.addEventListener("click", () => {
    if (_runsPage > 0) { _runsPage--; _renderRunsPage(); }
  });
  if (nextBtn) nextBtn.addEventListener("click", () => {
    const totalPages = Math.ceil(_runsData.length / _runsPageSize);
    if (_runsPage < totalPages - 1) { _runsPage++; _renderRunsPage(); }
  });
  if (pageSizeSel) pageSizeSel.addEventListener("change", () => {
    _runsPageSize = parseInt(pageSizeSel.value, 10);
    _runsPage = 0;
    _renderRunsPage();
  });
})();

// ── Analysis panel ──
let _stabilityData    = [];
let _failureGroups    = [];
let _catToNames       = {};      // category → Set<canonical_name>
let _ownerExpanded    = true;
let _anaRunsLimit     = 30;
let _riskMap          = {};

// ── Filter builder ──
const FILTER_FIELD_DEFS = [
  { key:"suite",       label:"Suite",             type:"enum"    },
  { key:"status",      label:"Status",            type:"enum",   staticOpts:["FLAKY","CONSISTENTLY_BROKEN","STABLE","INSUFFICIENT_DATA"] },
  { key:"owner",       label:"Owner",             type:"enum"    },
  { key:"category",    label:"Failure Category",  type:"enum"    },
  { key:"pass_rate",   label:"Pass Rate (%)",     type:"numeric" },
  { key:"run_count",   label:"Run Count",         type:"numeric" },
  { key:"runs_window", label:"Runs Window",       type:"select", staticOpts:[10,20,30,50] },
  { key:"test_name",   label:"Test Name",         type:"text"    },
];
const FILTER_OPS = {
  text:    [["contains","Contains"],["not_contains","Does not contain"],["equals","Equals"],
            ["not_equals","Does not equal"],["is_empty","Is empty"],["is_not_empty","Is not empty"]],
  enum:    [["is","Is"],["is_not","Is not"],["is_any_of","Is any of"],["is_none_of","Is none of"]],
  numeric: [["eq","="],["neq","≠"],["gt",">"],["lt","<"],["gte","≥"],["lte","≤"]],
  select:  [["eq","="]],
};
let _filterRows = [];          // [{id, conjunction, field, operator, value}]
let _filterPanelOpen = false;
let _filterEnumOpts = { owner:[], suite:[], category:[] };
let _filterInitialised = false;
let _ocOpenId = null;           // owner chip picker: which row ID is open

function _filterFieldDef(key) { return FILTER_FIELD_DEFS.find(d => d.key === key) || FILTER_FIELD_DEFS[0]; }
function _filterDefaultOp(type) { return FILTER_OPS[type][0][0]; }
function _filterDefaultVal(field, op) {
  const def = _filterFieldDef(field);
  if (def.type === "runs_window") return 30;
  if (def.type === "numeric")  return "";
  if (["is_empty","is_not_empty"].includes(op)) return "";
  return "";
}

function _addFilterRow() {
  const id = "fr" + Date.now();
  _filterRows.push({ id, conjunction:"and", field:"suite", operator:"contains", value:"" });
  _renderFilterPanel();
}

function _removeFilterRow(id) {
  _filterRows = _filterRows.filter(r => r.id !== id);
  _renderFilterPanel();
  _renderStabilityTable(_stabilityData, window._lastTrends || []);
}

async function _updateFilterRow(id, key, val) {
  const row = _filterRows.find(r => r.id === id);
  if (!row) return;

  // Determine if we need a full panel re-render (structure change) or just re-filter
  let structureChanged = false;

  if (key === "field") {
    const def = _filterFieldDef(val);
    row.field    = val;
    row.operator = _filterDefaultOp(def.type);
    row.value    = _filterDefaultVal(val, row.operator);
    structureChanged = true;
  } else if (key === "operator") {
    const prevOp = row.operator;
    row.operator = val;
    if (["is_empty","is_not_empty"].includes(val)) row.value = "";
    // switching between single-value and multi-value requires new input element
    const wasMulti = ["is_any_of","is_none_of"].includes(prevOp);
    const isMulti  = ["is_any_of","is_none_of"].includes(val);
    const wasNoVal = ["is_empty","is_not_empty"].includes(prevOp);
    const isNoVal  = ["is_empty","is_not_empty"].includes(val);
    if (isMulti && !Array.isArray(row.value)) row.value = [];
    if (!isMulti && Array.isArray(row.value)) row.value = "";
    structureChanged = wasMulti !== isMulti || wasNoVal !== isNoVal;
  } else {
    // value or conjunction change — update state only, no re-render needed
    row[key] = val;
  }

  // Runs Window change → re-fetch from API
  if (row.field === "runs_window" && key === "value") {
    _anaRunsLimit = parseInt(val, 10) || 30;
    _renderFilterPanel();
    await loadAnalysis();
    return;
  }

  if (structureChanged) _renderFilterPanel();
  else _updateFilterCount();          // keep badge in sync without destroying inputs
  _renderStabilityTable(_stabilityData, window._lastTrends || []);
}

function _multiSelectValues(id) {
  const sel = document.querySelector(`[data-id="${id}"] .filter-val-multi`);
  if (!sel) return [];
  return Array.from(sel.selectedOptions).map(o => o.value);
}

function _updateFilterCount() {
  const count = _filterRows.length;
  const badge = el("filter-count");
  if (badge) { badge.textContent = count; badge.style.display = count ? "" : "none"; }
}

function _renderFilterPanel() {
  const container = el("filter-rows-container");
  if (!container) return;

  const enumOpts = (field) => {
    const def = _filterFieldDef(field);
    if (def.staticOpts) return def.staticOpts.map(String);
    return _filterEnumOpts[field] || [];
  };

  container.innerHTML = _filterRows.map((row, i) => {
    const def   = _filterFieldDef(row.field);
    const ops   = FILTER_OPS[def.type] || FILTER_OPS.text;
    const noVal = ["is_empty","is_not_empty"].includes(row.operator);
    const multi = ["is_any_of","is_none_of"].includes(row.operator) && def.type === "enum";

    const conjHtml = i === 0
      ? `<span style="width:68px;flex-shrink:0;font-size:12px;color:var(--muted);text-align:center">Where</span>`
      : `<select class="filter-conj" onchange="_updateFilterRow('${row.id}','conjunction',this.value)">
           <option value="and"${row.conjunction==="and"?" selected":""}>and</option>
           <option value="or"${row.conjunction==="or"?" selected":""}>or</option>
         </select>`;

    const fieldHtml = `<select class="filter-field-sel" onchange="_updateFilterRow('${row.id}','field',this.value)">
      ${FILTER_FIELD_DEFS.map(d => `<option value="${d.key}"${d.key===row.field?" selected":""}>${d.label}</option>`).join("")}
    </select>`;

    const opHtml = `<select class="filter-op-sel" onchange="_updateFilterRow('${row.id}','operator',this.value)">
      ${ops.map(([k,l]) => `<option value="${k}"${k===row.operator?" selected":""}>${l}</option>`).join("")}
    </select>`;

    let valHtml = "";
    if (!noVal) {
      if (def.type === "text") {
        valHtml = `<input type="text" class="filter-val-input" value="${escHtml(String(row.value||""))}"
          oninput="_updateFilterRow('${row.id}','value',this.value)" placeholder="value…"/>`;
      } else if (def.type === "numeric") {
        valHtml = `<input type="number" class="filter-val-input" value="${row.value||""}"
          oninput="_updateFilterRow('${row.id}','value',this.value)" placeholder="0"/>`;
      } else if (def.type === "select") {
        const opts = enumOpts(row.field);
        valHtml = `<select class="filter-val-select" onchange="_updateFilterRow('${row.id}','value',this.value)">
          ${opts.map(o => `<option value="${o}"${String(o)===String(row.value)?" selected":""}>${o}</option>`).join("")}
        </select>`;
      } else if (row.field === "owner" || row.field === "suite") {
        valHtml = _renderOwnerChipWidget(row);
      } else if (def.type === "enum" && multi) {
        const opts = enumOpts(row.field);
        const sel  = Array.isArray(row.value) ? row.value : [];
        valHtml = `<select class="filter-val-multi" multiple
          onchange="_updateFilterRow('${row.id}','value',_multiSelectValues('${row.id}'))">
          ${opts.map(o => `<option value="${escHtml(o)}"${sel.includes(o)?" selected":""}>${escHtml(o)}</option>`).join("")}
        </select>`;
      } else if (def.type === "enum") {
        const opts = enumOpts(row.field);
        valHtml = `<select class="filter-val-select" onchange="_updateFilterRow('${row.id}','value',this.value)">
          <option value="">— choose —</option>
          ${opts.map(o => `<option value="${escHtml(o)}"${o===row.value?" selected":""}>${escHtml(o)}</option>`).join("")}
        </select>`;
      }
    }

    return `<div class="filter-row" data-id="${row.id}">
      ${conjHtml}${fieldHtml}${opHtml}${valHtml}
      <button class="filter-row-del" onclick="event.stopPropagation();_removeFilterRow('${row.id}')" title="Remove">×</button>
    </div>`;
  }).join("");

  // Update badge
  const count = _filterRows.length;
  const badge = el("filter-count");
  if (badge) { badge.textContent = count; badge.style.display = count ? "" : "none"; }
  const btn = el("filter-btn");
  if (btn) btn.classList.toggle("active", _filterPanelOpen);
}

// ── Owner chip filter widget ──────────────────────────────────────────────

function _ocSelected(row) {
  const multi = ["is_any_of","is_none_of"].includes(row.operator);
  if (multi) return Array.isArray(row.value) ? row.value : (row.value ? [row.value] : []);
  return row.value ? [row.value] : [];
}

function _ocChipsHtml(row) {
  const selected = _ocSelected(row);
  const MAX = 3;
  const visible  = selected.slice(0, MAX);
  const overflow = selected.length - MAX;

  let html = visible.map(name =>
    `<span class="oc-chip">
      <span class="oc-chip-name">${escHtml(name)}</span>
      <button class="oc-chip-x" data-rid="${row.id}" data-name="${escHtml(name)}"
        onclick="_ocRemove(this.dataset.rid,this.dataset.name)">✕</button>
    </span>`
  ).join("");

  if (overflow > 0) html += `<span class="oc-overflow">+${overflow} more</span>`;
  html += `<button class="oc-add-btn" data-rid="${row.id}" onclick="_ocOpenPicker(this.dataset.rid)">+ Add</button>`;
  if (selected.length >= 2) {
    html += `<button class="oc-clear-btn" data-rid="${row.id}" onclick="_ocClearAll(this.dataset.rid)">Clear all</button>`;
  }
  return html;
}

function _findFilterRow(id) {
  return _filterRows.find(r => r.id === id) || _riskFilterRows.find(r => r.id === id);
}

function _renderOwnerChipWidget(row, opts) {
  const owners   = opts || _filterEnumOpts[row.field] || [];
  const selected = _ocSelected(row);

  const listHtml = owners.map(name => {
    const checked = selected.includes(name) ? "checked" : "";
    return `<label class="oc-item">
      <input type="checkbox" ${checked} data-rid="${row.id}" data-name="${escHtml(name)}"
        onchange="_ocToggle(this.dataset.rid,this.dataset.name,this.checked)">
      <span>${escHtml(name)}</span>
    </label>`;
  }).join("");

  return `<div class="oc-wrap" id="oc-wrap-${row.id}">
    <div class="oc-chips" id="oc-chips-${row.id}">${_ocChipsHtml(row)}</div>
    <div class="oc-picker" id="oc-picker-${row.id}" style="display:none">
      <input class="oc-search" id="oc-search-${row.id}" placeholder="Search…"
        oninput="_ocSearch('${row.id}',this.value)"/>
      <div class="oc-list" id="oc-list-${row.id}">${listHtml}</div>
    </div>
  </div>`;
}

function _ocRedraw(rowId) {
  const row = _findFilterRow(rowId);
  if (!row) return;

  // Chips row: full replace (small, no inputs to lose focus)
  const chipsEl = el(`oc-chips-${rowId}`);
  if (chipsEl) chipsEl.innerHTML = _ocChipsHtml(row);

  // Sync checkboxes in picker — no re-render, preserves focus + scroll
  const listEl = el(`oc-list-${rowId}`);
  if (listEl) {
    const selected = _ocSelected(row);
    listEl.querySelectorAll("input[type=checkbox]").forEach(cb => {
      cb.checked = selected.includes(cb.dataset.name);
    });
  }

  if (_riskFilterRows.some(r => r.id === rowId)) {
    _updateRiskFilterCount();
    _applyRiskFilters();
  } else {
    _updateFilterCount();
    _renderStabilityTable(_stabilityData, window._lastTrends || []);
  }
}

function _ocOpenPicker(id) {
  if (_ocOpenId && _ocOpenId !== id) _ocClosePicker(_ocOpenId);
  _ocOpenId = id;
  const picker = el(`oc-picker-${id}`);
  if (!picker) return;
  picker.style.display = "";
  const search = el(`oc-search-${id}`);
  if (search) { search.value = ""; search.focus(); _ocSearch(id, ""); }
  setTimeout(() => document.addEventListener("click", _ocOutsideClick, { once: true }), 0);
}

function _ocClosePicker(id) {
  const picker = el(`oc-picker-${id}`);
  if (picker) picker.style.display = "none";
  _ocOpenId = null;
}

function _ocOutsideClick(e) {
  if (!_ocOpenId) return;
  const wrap = el(`oc-wrap-${_ocOpenId}`);
  if (wrap && wrap.contains(e.target)) {
    setTimeout(() => document.addEventListener("click", _ocOutsideClick, { once: true }), 0);
    return;
  }
  _ocClosePicker(_ocOpenId);
}

function _ocToggle(rowId, name, checked) {
  const row = _findFilterRow(rowId);
  if (!row) return;
  const multi = ["is_any_of","is_none_of"].includes(row.operator);
  if (multi) {
    const arr = _ocSelected(row).slice();
    if (checked && !arr.includes(name)) arr.push(name);
    else if (!checked) { const i = arr.indexOf(name); if (i >= 0) arr.splice(i, 1); }
    row.value = arr;
  } else {
    row.value = checked ? name : "";
    _ocClosePicker(rowId);
  }
  _ocRedraw(rowId);
}

function _ocRemove(rowId, name) {
  const row = _findFilterRow(rowId);
  if (!row) return;
  const multi = ["is_any_of","is_none_of"].includes(row.operator);
  row.value = multi ? _ocSelected(row).filter(v => v !== name) : "";
  _ocRedraw(rowId);
}

function _ocClearAll(rowId) {
  const row = _findFilterRow(rowId);
  if (!row) return;
  row.value = ["is_any_of","is_none_of"].includes(row.operator) ? [] : "";
  _ocRedraw(rowId);
}

function _ocSearch(rowId, query) {
  const listEl = el(`oc-list-${rowId}`);
  if (!listEl) return;
  const q = query.trim().toLowerCase();
  listEl.querySelectorAll(".oc-item").forEach(item => {
    const name = (item.querySelector("span") || item).textContent.trim().toLowerCase();
    item.style.display = !q || name.includes(q) ? "" : "none";
  });
}

// ── Risk panel filter system ──────────────────────────────────────────────

const RISK_FILTER_DEFS = [
  { key:"owner",  label:"Owner",  type:"enum" },
  { key:"module", label:"Module", type:"enum" },
  { key:"tier",   label:"Tier",   type:"enum", staticOpts:["CRITICAL","HIGH","MEDIUM","LOW"] },
];

let _riskFilterRows       = [];
let _riskFilterPanelOpen  = false;
let _riskFilterEnumOpts   = { owner:[], module:[], tier:["CRITICAL","HIGH","MEDIUM","LOW"] };

function _rfEnumOpts(field) {
  const def = RISK_FILTER_DEFS.find(d => d.key === field);
  if (def?.staticOpts) return def.staticOpts.map(String);
  return _riskFilterEnumOpts[field] || [];
}

function _updateRiskFilterCount() {
  const badge = el("rf-count");
  const n = _riskFilterRows.length;
  if (badge) { badge.textContent = n; badge.style.display = n ? "" : "none"; }
}

function _addRiskFilterRow() {
  const id = "rr" + Date.now();
  _riskFilterRows.push({ id, conjunction:"and", field:"owner", operator:"is_any_of", value:[] });
  _renderRiskFilterPanel();
}

function _removeRiskFilterRow(id) {
  _riskFilterRows = _riskFilterRows.filter(r => r.id !== id);
  _renderRiskFilterPanel();
  _applyRiskFilters();
}

function _updateRiskFilterRow(id, key, val) {
  const row = _riskFilterRows.find(r => r.id === id);
  if (!row) return;
  let structureChanged = false;
  if (key === "field") {
    row.field    = val;
    row.operator = "is_any_of";
    row.value    = [];
    structureChanged = true;
  } else if (key === "operator") {
    const wasMulti = ["is_any_of","is_none_of"].includes(row.operator);
    const isMulti  = ["is_any_of","is_none_of"].includes(val);
    row.operator = val;
    if (isMulti  && !Array.isArray(row.value)) row.value = [];
    if (!isMulti &&  Array.isArray(row.value)) row.value = "";
    structureChanged = wasMulti !== isMulti;
  } else {
    row[key] = val;
  }
  if (structureChanged) _renderRiskFilterPanel();
  else _updateRiskFilterCount();
  _applyRiskFilters();
}

function _renderRiskFilterPanel() {
  const container = el("rf-rows-container");
  if (!container) return;

  container.innerHTML = _riskFilterRows.map((row, i) => {
    const conjHtml = i === 0
      ? `<span style="width:68px;flex-shrink:0;font-size:12px;color:var(--muted);text-align:center">Where</span>`
      : `<select class="filter-conj" onchange="_updateRiskFilterRow('${row.id}','conjunction',this.value)">
           <option value="and"${row.conjunction==="and"?" selected":""}>and</option>
           <option value="or"${row.conjunction==="or"?" selected":""}>or</option>
         </select>`;

    const fieldHtml = `<select class="filter-field-sel" onchange="_updateRiskFilterRow('${row.id}','field',this.value)">
      ${RISK_FILTER_DEFS.map(d => `<option value="${d.key}"${d.key===row.field?" selected":""}>${d.label}</option>`).join("")}
    </select>`;

    const opHtml = `<select class="filter-op-sel" onchange="_updateRiskFilterRow('${row.id}','operator',this.value)">
      ${FILTER_OPS.enum.map(([k,l]) => `<option value="${k}"${k===row.operator?" selected":""}>${l}</option>`).join("")}
    </select>`;

    const valHtml = _renderOwnerChipWidget(row, _rfEnumOpts(row.field));

    return `<div class="filter-row" data-id="${row.id}">
      ${conjHtml}${fieldHtml}${opHtml}${valHtml}
      <button class="filter-row-del" onclick="event.stopPropagation();_removeRiskFilterRow('${row.id}')" title="Remove">×</button>
    </div>`;
  }).join("");

  _updateRiskFilterCount();
  const btn = el("rf-btn");
  if (btn) btn.classList.toggle("active", _riskFilterPanelOpen);
}

function _toggleRiskFilter() {
  _riskFilterPanelOpen = !_riskFilterPanelOpen;
  const wrap = el("rf-panel-wrap");
  if (wrap) wrap.style.display = _riskFilterPanelOpen ? "" : "none";
  const btn = el("rf-btn");
  if (btn) btn.classList.toggle("active", _riskFilterPanelOpen);
  if (_riskFilterPanelOpen) {
    setTimeout(() => document.addEventListener("click", _rfOutsideClick, { once: true }), 0);
  }
}

function _rfOutsideClick(e) {
  const bar = el("rf-bar");
  if (bar && bar.contains(e.target)) {
    setTimeout(() => document.addEventListener("click", _rfOutsideClick, { once: true }), 0);
    return;
  }
  _riskFilterPanelOpen = false;
  const wrap = el("rf-panel-wrap");
  if (wrap) wrap.style.display = "none";
  const btn = el("rf-btn");
  if (btn) btn.classList.remove("active");
}

function _toggleFilterPanel() {
  _filterPanelOpen = !_filterPanelOpen;
  const wrap = el("filter-panel-wrap");
  if (wrap) wrap.style.display = _filterPanelOpen ? "" : "none";
  const btn = el("filter-btn");
  if (btn) btn.classList.toggle("active", _filterPanelOpen);
  if (_filterPanelOpen) {
    setTimeout(() => {
      document.addEventListener("click", _filterOutsideClick, { once: true });
    }, 0);
  }
}

function _filterOutsideClick(e) {
  const bar = el("filter-bar");
  if (bar && bar.contains(e.target)) {
    // clicked inside — re-attach listener
    setTimeout(() => {
      document.addEventListener("click", _filterOutsideClick, { once: true });
    }, 0);
    return;
  }
  _filterPanelOpen = false;
  const wrap = el("filter-panel-wrap");
  if (wrap) wrap.style.display = "none";
  const btn = el("filter-btn");
  if (btn) btn.classList.remove("active");
}

// ── Filter evaluation engine ──

function _evalText(actual, op, val) {
  const a = (actual || "").toLowerCase();
  const v = (val || "").toLowerCase();
  switch (op) {
    case "contains":     return a.includes(v);
    case "not_contains": return !a.includes(v);
    case "equals":       return a === v;
    case "not_equals":   return a !== v;
    case "is_empty":     return !actual;
    case "is_not_empty": return !!actual;
    default: return true;
  }
}
function _evalEnum(actual, op, val) {
  const vals = Array.isArray(val) ? val : (val ? [val] : []);
  switch (op) {
    case "is":        return actual === val;
    case "is_not":    return actual !== val;
    case "is_any_of": return vals.includes(actual);
    case "is_none_of":return !vals.includes(actual);
    default: return true;
  }
}
function _evalNumeric(actual, op, val) {
  const n = parseFloat(val);
  if (isNaN(n)) return true;
  switch (op) {
    case "eq":  return actual === n;
    case "neq": return actual !== n;
    case "gt":  return actual > n;
    case "lt":  return actual < n;
    case "gte": return actual >= n;
    case "lte": return actual <= n;
    default: return true;
  }
}

function _evalFilterRow(row, r) {
  const { field, operator, value } = row;
  if (field === "runs_window") return true; // API-level param, not a row filter
  const blank = value === "" || (Array.isArray(value) && value.length === 0);
  if (blank && !["is_empty","is_not_empty"].includes(operator)) return true; // blank = no filter
  switch (field) {
    case "test_name": return _evalText(r.canonical_name, operator, value);
    case "owner":     return _evalEnum(r.owner || "", operator, value);
    case "suite":     return _evalText(r.suite || "", operator, value);
    case "status":    return _evalEnum(r.classification || "", operator, value);
    case "category": {
      const check = (cat) => (_catToNames[cat] || new Set()).has(r.canonical_name);
      if (operator === "is")        return check(value);
      if (operator === "is_not")    return !check(value);
      if (operator === "is_any_of") return (Array.isArray(value) ? value : []).some(check);
      if (operator === "is_none_of")return !(Array.isArray(value) ? value : []).some(check);
      return true;
    }
    case "pass_rate": return _evalNumeric((r.pass_rate ?? 0) * 100, operator, value);
    case "run_count": return _evalNumeric(r.run_count ?? 0, operator, value);
    default: return true;
  }
}

function _applyAllFilters(data) {
  if (!_filterRows.length) return data;
  const active = _filterRows.filter(row => row.field !== "runs_window");
  if (!active.length) return data;
  return data.filter(r => {
    let result = _evalFilterRow(active[0], r);
    for (let i = 1; i < active.length; i++) {
      const rowResult = _evalFilterRow(active[i], r);
      result = active[i].conjunction === "and" ? result && rowResult : result || rowResult;
    }
    return result;
  });
}

function _buildCatToNames(groups) {
  _catToNames = {};
  groups.forEach(g => {
    const cat = g.category || "Unknown";
    if (!_catToNames[cat]) _catToNames[cat] = new Set();
    (g.affected_canonical_names || []).forEach(n => _catToNames[cat].add(n));
  });
}

async function loadAnalysis() {
  const proj  = currentProject ? `&project=${encodeURIComponent(currentProject)}` : "";
  const limitQ = `&limit=${_anaRunsLimit}`;
  el("stability-body").innerHTML = `<tr><td colspan="8" class="loading">Loading…</td></tr>`;
  el("failures-body").innerHTML  = `<tr><td colspan="7" class="loading">Loading…</td></tr>`;

  // Sync the runs_window filter row to the current limit
  const rwRow = _filterRows.find(r => r.field === "runs_window");
  if (rwRow) rwRow.value = _anaRunsLimit;

  const [stability, trends, groups, riskList] = await Promise.all([
    apiFetch(`/api/stability?min_runs=2${proj}${limitQ}`).catch(() => []),
    apiFetch(`/api/stability/trends?min_runs=2${proj}${limitQ}`).catch(() => []),
    apiFetch(`/api/failure-groups?${proj.replace(/^&/,"")}`).catch(() => []),
    apiFetch(`/api/risk?min_runs=2${proj}`).catch(() => []),
  ]);

  _stabilityData = stability;
  _failureGroups = groups;

  _riskMap = {};
  riskList.forEach(p => { _riskMap[p.canonical_name] = { risk_pct: p.risk_pct, tier: p.tier }; });

  // Build category map + populate dynamic enum options
  _buildCatToNames(groups);
  _filterEnumOpts.owner    = [...new Set(stability.map(r => r.owner).filter(Boolean))].sort();
  _filterEnumOpts.suite    = [...new Set(stability.map(r => r.suite).filter(Boolean))].sort();
  _filterEnumOpts.category = Object.keys(_catToNames).sort();

  // First load: pre-populate default Runs Window row
  if (!_filterInitialised) {
    _filterInitialised = true;
    _filterRows = [{ id:"_rw", conjunction:"and", field:"runs_window", operator:"eq", value:_anaRunsLimit }];
  }

  _renderFilterPanel();
  _renderAnalysisStats(stability);
  _renderStreakPanel(stability);
  _renderStabilityTable(stability, trends);
  _renderOwnerSummary(stability);
  _renderFailureGroups(groups);
}

function _renderAnalysisStats(data) {
  const counts = { FLAKY: 0, CONSISTENTLY_BROKEN: 0, STABLE: 0, INSUFFICIENT_DATA: 0 };
  data.forEach(r => { if (r.classification in counts) counts[r.classification]++; });
  el("analysis-stats").innerHTML = `
    <div class="stat-card"><div class="label">Flaky</div><div class="value flaky">${counts.FLAKY}</div></div>
    <div class="stat-card"><div class="label">Broken</div><div class="value fail">${counts.CONSISTENTLY_BROKEN}</div></div>
    <div class="stat-card"><div class="label">Stable</div><div class="value pass">${counts.STABLE}</div></div>
    <div class="stat-card"><div class="label">Insufficient</div><div class="value" style="color:var(--muted)">${counts.INSUFFICIENT_DATA}</div></div>
  `;
}

// Feature 1 — Active failure streak alert
let _streakOpen = true;
function _renderStreakPanel(data) {
  const panel = el("streak-panel");
  if (!panel) return;
  const streakers = data
    .filter(r => r.current_streak <= -2)
    .sort((a, b) => a.current_streak - b.current_streak);
  if (!streakers.length) { panel.innerHTML = ""; return; }
  panel.innerHTML = `
    <div class="streak-alert${_streakOpen ? "" : " collapsed"}">
      <div class="streak-alert-title">
        &#9888; Active Failure Streaks — needs immediate attention
        <span class="streak-count" style="margin-left:6px;font-size:11px;font-weight:400;opacity:0.7">${streakers.length} test${streakers.length > 1 ? "s" : ""}</span>
        <svg class="streak-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div class="streak-body">
        ${streakers.map(r => `
          <div class="streak-item">
            <span class="streak-count">${Math.abs(r.current_streak)} consecutive failures</span>
            <span style="flex:1;word-break:break-word">${escHtml(r.canonical_name)}</span>
            ${r.owner ? `<span style="font-size:11px;color:var(--muted)">${escHtml(r.owner)}</span>` : ""}
          </div>`).join("")}
      </div>
    </div>`;
  panel.querySelector(".streak-alert-title").addEventListener("click", () => {
    _streakOpen = !_streakOpen;
    panel.querySelector(".streak-alert").classList.toggle("collapsed", !_streakOpen);
  });
}

// Feature 3 — Stability table with filter engine
function _renderStabilityTable(data, trends) {
  window._lastTrends = trends;
  const body = el("stability-body");
  if (!body) return;

  let rows = _applyAllFilters(data);

  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7" class="empty">No matching tests. Adjust filters or ingest more runs.</td></tr>`;
    return;
  }

  body.innerHTML = rows.map(r => {
    const cls = r.classification.toLowerCase().replace("_", "-");
    const badgeType = cls === "consistently-broken" ? "broken" : cls === "insufficient-data" ? "insufficient" : cls;
    const trendCell = _sparklineTrendCell(r.sparkline);
    const passRatePct = Math.round((r.pass_rate ?? 0) * 100);
    const prColor = passRatePct >= 70 ? "var(--pass)" : passRatePct >= 40 ? "var(--flaky)" : "var(--fail)";
    const flipHtml = r.flip_score != null
      ? `<span class="pass-rate-flip">↕ ${r.flip_score.toFixed(2)} flips</span>`
      : "";
    return `<tr>
      <td style="font-weight:500">${escHtml(r.canonical_name)}</td>
      <td style="font-size:12px;color:var(--muted)">${r.owner ? escHtml(r.owner) : "\u2014"}</td>
      <td><span class="cell-trunc" style="font-size:12px;color:var(--muted)" title="${escHtml(r.suite || "")}">${r.suite ? escHtml(r.suite) : "\u2014"}</span></td>
      <td>${badge(badgeType, r.classification.replace(/_/g," "))}</td>
      <td><div class="pass-rate-cell"><span style="font-weight:700;color:${prColor}">${passRatePct}%</span>${flipHtml}</div></td>
      <td>${trendCell}</td>
      <td>${_heatmapHistory(r.sparkline)}</td>
    </tr>`;
  }).join("");
}

// Feature 4 — Owner health summary
function _renderOwnerSummary(data) {
  const wrap = el("owner-summary-wrap");
  if (!wrap) return;
  if (!data.length) { wrap.style.display = "none"; return; }

  const owners = {};
  data.forEach(r => {
    const owner = r.owner || "(unassigned)";
    if (!owners[owner]) owners[owner] = { flaky: 0, broken: 0, total: 0 };
    owners[owner].total++;
    if (r.classification === "FLAKY") owners[owner].flaky++;
    if (r.classification === "CONSISTENTLY_BROKEN") owners[owner].broken++;
  });

  const sorted = Object.entries(owners).sort((a, b) => (b[1].flaky + b[1].broken) - (a[1].flaky + a[1].broken));
  el("owner-table-body").innerHTML = sorted.map(([owner, s]) => `
    <tr>
      <td style="font-weight:500">${escHtml(owner)}</td>
      <td style="color:var(--flaky);font-weight:600">${s.flaky || "—"}</td>
      <td style="color:var(--fail);font-weight:600">${s.broken || "—"}</td>
      <td style="color:var(--muted)">${s.total}</td>
    </tr>`).join("");
  wrap.style.display = "block";
}

function toggleOwnerSummary() {
  _ownerExpanded = !_ownerExpanded;
  el("owner-table-wrap").style.display = _ownerExpanded ? "block" : "none";
  el("owner-toggle-icon").textContent = _ownerExpanded ? "▼" : "▶";
}

function _renderFailureGroups(groups) {
  const body = el("failures-body");
  if (!groups.length) {
    body.innerHTML = `<tr><td colspan="7" class="empty">No recurring failure groups found.</td></tr>`;
    return;
  }
  body.innerHTML = groups.map((g, i) => {
    const rowId = "fg-detail-" + i;
    const detailRow = g.message ? `
      <tr class="detail-row hidden" id="${rowId}">
        <td colspan="7"><pre class="stack">${escHtml(g.message)}</pre></td>
      </tr>` : "";
    const expandBtn = g.message
      ? `<button class="expand-btn" onclick="toggleRow('${rowId}')" title="Show message">▸</button> ` : "";
    return `<tr>
      <td class="mono" style="font-size:11px">${expandBtn}${escHtml(truncate(g.fingerprint,16))}</td>
      <td>${fmt(g.occurrence_count)}</td>
      <td>${fmt(g.affected_tests)}</td>
      <td style="font-size:12px">${escHtml(g.error_type ?? "—")}</td>
      <td style="font-size:12px;max-width:280px;word-break:break-word">${escHtml(truncate(g.message,80))}</td>
      <td style="white-space:nowrap;font-size:12px">${g.last_seen_seq != null ? "Run #" + g.last_seen_seq : "—"}</td>
      <td class="bug-cell" data-fp="${escHtml(g.fingerprint)}"></td>
    </tr>${detailRow}`;
  }).join("");

  // Populate bug cells with interactive content (cannot use innerHTML with event handlers)
  const bugCells = body.querySelectorAll(".bug-cell");
  groups.forEach((g, i) => {
    if (bugCells[i]) _renderBugCell(bugCells[i], g.fingerprint, g.bug_links || []);
  });

  _makeTableResizable("failures-table");
}

function _renderBugCell(cell, fingerprint, links) {
  cell.innerHTML = "";
  links.forEach(link => {
    const chip = document.createElement("span");
    chip.className = "bug-chip";
    const a = document.createElement("a");
    a.className = "bug-chip-link";
    const safeHref = _safeUrl(link.bug_url);
    if (safeHref) {
      a.href = safeHref;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    }
    a.textContent = link.label || link.bug_url;
    const x = document.createElement("button");
    x.className = "bug-chip-x";
    x.title = "Remove";
    x.textContent = "×";
    x.addEventListener("click", (e) => {
      e.stopPropagation();
      _removeBugLink(fingerprint, link.id);
    });
    chip.appendChild(a);
    chip.appendChild(x);
    cell.appendChild(chip);
  });

  const addBtn = document.createElement("button");
  addBtn.className = "bug-add-btn";
  addBtn.title = "Link a bug";
  addBtn.textContent = "+";
  addBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    addBtn.style.display = "none";
    const input = document.createElement("input");
    input.className = "bug-input";
    input.placeholder = "Paste bug URL…";
    input.type = "url";
    cell.appendChild(input);
    input.focus();

    const commit = () => {
      const url = input.value.trim();
      if (url) _addBugLink(fingerprint, url);
      else { input.remove(); addBtn.style.display = ""; }
    };
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); commit(); }
      if (ev.key === "Escape") { input.remove(); addBtn.style.display = ""; }
    });
    input.addEventListener("blur", () => { setTimeout(commit, 150); });
  });
  cell.appendChild(addBtn);
}

async function _addBugLink(fingerprint, url) {
  try {
    await fetch(`/api/failure-groups/${encodeURIComponent(fingerprint)}/bug-links`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    loadAnalysis();
  } catch (err) {
    console.error("Failed to add bug link", err);
  }
}

async function _removeBugLink(fingerprint, linkId) {
  try {
    await fetch(`/api/failure-groups/${encodeURIComponent(fingerprint)}/bug-links/${linkId}`, {
      method: "DELETE",
    });
    loadAnalysis();
  } catch (err) {
    console.error("Failed to remove bug link", err);
  }
}

function toggleRow(id) {
  const row = el(id);
  if (row) row.classList.toggle("hidden");
}

// ── Risk panel ──
let _riskData = [];
let _riskCatMap = {};  // canonical_name → top failure category for Priorities table

const TIER_COLOR = {
  CRITICAL: "#e74c3c",
  HIGH:     "#e67e22",
  MEDIUM:   "#f39c12",
  LOW:      "#27ae60",
};
const TIER_LABEL = {
  CRITICAL: "Critical",
  HIGH:     "High",
  MEDIUM:   "Medium",
  LOW:      "Low",
};
const SIGNAL_LABEL = {
  volatility:       "Volatile",
  failure_burden:   "Failing",
  recent_decline:   "Declining",
  fail_streak:      "On fail streak",
  duration_spike:   "Slowing",
};
const SIGNAL_BG = {
  volatility:       "rgba(251,146,60,0.2)",
  failure_burden:   "rgba(248,113,113,0.2)",
  recent_decline:   "rgba(230,126,34,0.2)",
  fail_streak:      "rgba(231,76,60,0.2)",
  duration_spike:   "rgba(136,146,176,0.2)",
};
const SIGNAL_TOOLTIP = {
  volatility:       "Flip score — how often this test switches between pass and fail across consecutive runs. High % means it alternates unpredictably.",
  failure_burden:   "All-time failure rate — percentage of all observed runs that ended in failure. 100% means the test has never passed.",
  recent_decline:   "Recent decline — the last 3 runs have a higher failure rate than the historical average. The test is getting worse recently.",
  fail_streak:      "Active fail streak — the test is currently on consecutive failing runs. 100% means 3 or more failures in a row right now.",
  duration_spike:   "Duration growth — the test is steadily getting slower (rising execution time trend). Often an early warning before flakiness or timeouts.",
};

function _tierBadge(tier) {
  const cls = tier.toLowerCase();
  const lbl = TIER_LABEL[tier] || tier;
  return `<span class="badge tier-${cls}">${lbl}</span>`;
}

function _riskRing(pct, tier) {
  const color = TIER_COLOR[tier] || "#888";
  const r = 14, sw = 3.5, sz = (r + sw) * 2;
  const circ = 2 * Math.PI * r;
  const arc  = circ * pct / 100;
  const tip  = pct >= 75 ? `${pct}% risk — very likely to fail in the next run`
             : pct >= 50 ? `${pct}% risk — likely to fail in the next run`
             : pct >= 25 ? `${pct}% risk — some chance of failing in the next run`
             :              `${pct}% risk — relatively stable, low chance of failing`;
  return `<div class="risk-ring-cell" onmouseenter="_trendTip(event,this)" onmouseleave="_hmHide()"
    data-tip="${escHtml(tip)}">
    <svg width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}" style="transform:rotate(-90deg);flex-shrink:0">
      <circle cx="${sz/2}" cy="${sz/2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="${sw}"/>
      <circle cx="${sz/2}" cy="${sz/2}" r="${r}" fill="none" stroke="${color}" stroke-width="${sw}"
              stroke-linecap="round" stroke-dasharray="${arc.toFixed(2)} ${(circ-arc).toFixed(2)}"/>
    </svg>
    <span style="font-weight:700;font-size:13px;color:${color}">${pct}%</span>
  </div>`;
}

function _topSignals(signals) {
  const entries = Object.entries(signals)
    .filter(([,v]) => Math.round(v * 100) > 0)
    .sort((a,b) => b[1] - a[1])
    .slice(0, 2);
  return entries.map(([k, v]) => {
    const bg = SIGNAL_BG[k] || "rgba(136,146,176,0.2)";
    const lbl = SIGNAL_LABEL[k] || k;
    const tip = SIGNAL_TOOLTIP[k] || "";
    return `<span class="signal-pill" style="background:${bg}" data-tooltip="${tip}">${lbl} ${(v * 100).toFixed(0)}%</span>`;
  }).join("");
}

function _renderRiskTable(data) {
  const body = el("risk-body");
  if (!data.length) {
    body.innerHTML = `<tr><td colspan="9" class="empty">No tests at risk. Ingest at least 2 runs.</td></tr>`;
    return;
  }
  body.innerHTML = data.map(p => `<tr data-canonical="${escHtml(p.canonical_name)}">
    <td style="font-weight:500">${escHtml(p.display_name)}</td>
    <td><span class="cell-trunc" style="font-size:12px;color:var(--muted)" title="${escHtml(p.module)}">${escHtml(p.module)}</span></td>
    <td style="font-size:12px;color:var(--muted)">${p.owner ? escHtml(p.owner) : "\u2014"}</td>
    <td>${_riskRing(p.risk_pct, p.tier)}</td>
    <td>${_tierBadge(p.tier)}</td>
    <td style="font-size:12px">${_topSignals(p.signals)}</td>
    <td style="font-size:12px;color:var(--muted)">${escHtml(_riskCatMap[p.canonical_name] || "\u2014")}</td>
    <td>${_heatmapHistory(p.sparkline)}</td>
    <td class="col-num" style="font-size:12px;color:var(--muted)">${p.run_count}</td>
  </tr>`).join("");
  _makeTableResizable("risk-table");
}

function _applyRiskFilters() {
  const search = (el("risk-search")?.value || "").toLowerCase();
  let filtered = _riskData;
  if (search) {
    filtered = filtered.filter(p =>
      p.display_name.toLowerCase().includes(search) ||
      p.canonical_name.toLowerCase().includes(search)
    );
  }
  if (_riskFilterRows.length) {
    filtered = filtered.filter(p => {
      let result = _evalRiskRow(_riskFilterRows[0], p);
      for (let i = 1; i < _riskFilterRows.length; i++) {
        const r = _evalRiskRow(_riskFilterRows[i], p);
        result = _riskFilterRows[i].conjunction === "and" ? result && r : result || r;
      }
      return result;
    });
  }
  _renderRiskTable(filtered);
}

function _evalRiskRow(row, p) {
  const { field, operator, value } = row;
  const blank = value === "" || (Array.isArray(value) && value.length === 0);
  if (blank) return true;
  const actual = field === "owner"  ? (p.owner  || "")
               : field === "module" ? (p.module || "")
               : field === "tier"   ? (p.tier   || "")
               : "";
  return _evalEnum(actual, operator, value);
}

async function loadRisk() {
  const body = el("risk-body");
  const statsRow = el("risk-stats");
  body.innerHTML = `<tr><td colspan="9" class="loading">Loading risk predictions…</td></tr>`;
  statsRow.innerHTML = "";
  ariLog("info", `Fetching risk predictions (project=${currentProject || "(all)"})`);
  try {
    const qs = currentProject ? `?project=${encodeURIComponent(currentProject)}` : "";
    const [riskData, riskGroups] = await Promise.all([
      apiFetch("/api/risk" + qs),
      apiFetch("/api/failure-groups" + qs).catch(() => []),
    ]);
    _riskData = riskData;
    ariLog("ok", `${_riskData.length} test(s) analyzed.`);

    // Build canonical_name → top failure category map
    // Groups arrive sorted by occurrence_count DESC; first group that includes a test wins
    _riskCatMap = {};
    riskGroups.forEach(g => {
      const cat = g.category || "Unknown";
      (g.affected_canonical_names || []).forEach(name => {
        if (!_riskCatMap[name]) _riskCatMap[name] = cat;
      });
    });

    // Tier counts
    const counts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    _riskData.forEach(p => { if (p.tier in counts) counts[p.tier]++; });
    statsRow.innerHTML = `
      <div class="stat-card"><div class="label">&#128308; Critical</div><div class="value" style="color:#e74c3c">${counts.CRITICAL}</div></div>
      <div class="stat-card"><div class="label">&#128992; High</div><div class="value" style="color:#e67e22">${counts.HIGH}</div></div>
      <div class="stat-card"><div class="label">&#128993; Medium</div><div class="value" style="color:#f39c12">${counts.MEDIUM}</div></div>
      <div class="stat-card"><div class="label">&#128994; Low</div><div class="value" style="color:#27ae60">${counts.LOW}</div></div>
      <div class="stat-card"><div class="label">Total Analyzed</div><div class="value" style="color:var(--muted)">${_riskData.length}</div></div>
    `;

    // Populate filter enum options
    _riskFilterEnumOpts.module = [...new Set(_riskData.map(p => p.module).filter(Boolean))].sort();
    _riskFilterEnumOpts.owner  = [...new Set(_riskData.map(p => p.owner).filter(Boolean))].sort();
    _renderRiskFilterPanel();
    _renderRiskTable(_riskData);
  } catch(e) {
    ariLog("error", `Risk load failed: ${e.message}`);
    body.innerHTML = `<tr><td colspan="9" class="error-msg">&#10060; ${escHtml(e.message)} — <a href="javascript:loadRisk()" style="color:var(--accent)">Retry</a></td></tr>`;
    statsRow.innerHTML = "";
  }
}

// Wire search input
el("risk-search").addEventListener("input", _applyRiskFilters);

// ── Generic [data-tooltip] tooltip (JS-positioned so it flips when near viewport edge) ──
(function() {
  const tip = document.createElement("div");
  tip.id = "ari-tooltip";
  document.body.appendChild(tip);

  const GAP = 8;          // px gap between target and tooltip
  const TIP_W = 280;      // must match CSS width

  document.addEventListener("mouseover", e => {
    const target = e.target.closest("[data-tooltip]");
    if (!target || !target.dataset.tooltip) return;
    tip.textContent = target.dataset.tooltip;
    tip.classList.add("visible");
    _positionTip(target);
  });
  document.addEventListener("mouseout", e => {
    if (!e.target.closest("[data-tooltip]")) return;
    tip.classList.remove("visible");
  });
  document.addEventListener("scroll", () => tip.classList.remove("visible"), true);

  function _positionTip(pill) {
    const r   = pill.getBoundingClientRect();
    const th  = tip.offsetHeight || 60;   // fallback before first paint
    const vw  = window.innerWidth;
    const vh  = window.innerHeight;

    // Prefer above; flip below if not enough room
    let top;
    if (r.top - th - GAP >= 0) {
      top = r.top - th - GAP;
    } else {
      top = r.bottom + GAP;
    }

    // Center horizontally on the pill, clamp to viewport
    let left = r.left + r.width / 2 - TIP_W / 2;
    left = Math.max(8, Math.min(left, vw - TIP_W - 8));

    tip.style.top  = top  + "px";
    tip.style.left = left + "px";
  }
})();


// ── Chat panel ──
const chatMessages = el("chat-messages");
const chatInput = el("chat-input");
const chatSend = el("chat-send");

// Track conversation stats for Option D summary
const _chat = { exchanges: 0, topics: [], history: [] };

function chatSuggest(btn) {
  const text = btn.querySelector(".sug-text").textContent;
  chatInput.value = text;
  chatInput.dispatchEvent(new Event("input"));
  sendChat();
}

function _renderStaticCards(grid) {
  const defaults = [
    { icon: "🔥", metric: null, question: "What broke in the latest run?" },
    { icon: "🚨", metric: null, question: "What new failures were introduced?" },
    { icon: "⚠️", metric: null, question: "What tests are most likely to fail next?" },
    { icon: "🧠", metric: null, question: "What is the root cause of these failures?" },
  ];
  grid.innerHTML = "";
  defaults.forEach(c => grid.appendChild(_makeCardEl(c.icon, c.metric, c.question)));
}

function _makeCardEl(icon, metric, question) {
  const btn = document.createElement("button");
  btn.className = "chat-suggestion";
  btn.addEventListener("click", () => {
    chatInput.value = question;
    chatInput.dispatchEvent(new Event("input"));
    sendChat();
  });
  let inner = `<span class="sug-icon">${icon}</span>`;
  inner += `<span class="sug-text">${question}</span>`;
  if (metric) inner += `<span class="sug-metric">${metric}</span>`;
  btn.innerHTML = inner;
  return btn;
}

async function loadHomepageCards() {
  const grid = el("chat-suggestions");
  if (!grid) return;
  const qs = currentProject ? `?project=${encodeURIComponent(currentProject)}` : "";
  try {
    const data = await apiFetch(`/api/homepage-cards${qs}`);
    const cards = (data && data.cards) ? data.cards : [];
    const available = cards.filter(c => c.available !== false);
    if (available.length === 0) {
      _renderStaticCards(grid);
      return;
    }
    grid.innerHTML = "";
    available.forEach(c => grid.appendChild(_makeCardEl(c.icon, c.metric, c.question)));
  } catch (_) {
    _renderStaticCards(grid);
  }
}

function chatShowMessages() {
  const welcome = el("chat-welcome");
  const msgs = el("chat-messages");
  if (welcome && welcome.style.display !== "none") {
    welcome.style.display = "none";
    msgs.style.display = "flex";
  }
}

function appendMessage(role, text) {
  chatShowMessages();
  const msgs = el("chat-messages");
  const div = document.createElement("div");
  div.className = "msg " + role;
  if (role === "assistant") {
    div.dataset.rawText = text;  // preserve original markdown for copy
    div.innerHTML = renderMarkdown(text);
    // Copy button
    const copyBtn = document.createElement("button");
    copyBtn.className = "msg-copy-btn";
    copyBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`;
    copyBtn.addEventListener("click", () => {
      const raw = div.dataset.rawText || "";
      navigator.clipboard.writeText(raw).then(() => {
        copyBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Copied`;
        copyBtn.classList.add("copied");
        setTimeout(() => {
          copyBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`;
          copyBtn.classList.remove("copied");
        }, 2000);
      }).catch(() => {
        // Fallback for insecure contexts
        const ta = document.createElement("textarea");
        ta.value = raw;
        ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        copyBtn.textContent = "Copied";
        copyBtn.classList.add("copied");
        setTimeout(() => { copyBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`; copyBtn.classList.remove("copied"); }, 2000);
      });
    });
    div.appendChild(copyBtn);
  } else {
    div.textContent = text;
  }
  msgs.appendChild(div);
  const body = el("chat-body");
  if (role === "assistant") {
    // Scroll so the TOP of the new answer is visible, not the bottom
    requestAnimationFrame(() => div.scrollIntoView({ behavior: "smooth", block: "start" }));
  } else {
    // User message and status indicators: scroll to bottom so the reply area is ready
    body.scrollTop = body.scrollHeight;
  }
  return div;
}

function appendSources(afterEl, sources) {
  if (!sources || !sources.length) return;
  const old = el("chat-sources");
  if (old) old.remove();
  const outer = document.createElement("div");
  outer.className = "source-outer";
  outer.id = "chat-sources";
  const lbl = document.createElement("div");
  lbl.className = "source-section-label";
  lbl.textContent = "Evidence";
  outer.appendChild(lbl);
  const wrap = document.createElement("div");
  wrap.className = "source-row";
  outer.appendChild(wrap);
  const VISIBLE = 3;
  const hidden = [];
  // Store full list for drawer prev/next nav
  _evNav.sources = sources.slice();
  _evNav.idx = 0;
  sources.forEach((s, idx) => {
    const card = document.createElement("div");
    card.className = "source-card";
    const icon = escHtml(s.icon || "");
    const label = escHtml(s.label || "");
    const meta = escHtml(s.meta || "");
    card.title = "Click to view evidence details";
    card.innerHTML = `<div><span class="src-icon">${icon}</span><span class="src-label">${label}</span></div><div class="src-meta">${meta}</div><span class="src-ext" title="Open full page">↗</span>`;

    // Primary click: open Evidence Drawer
    card.addEventListener("click", (e) => {
      // If the tiny ↗ icon is clicked, navigate instead
      if (e.target.classList.contains("src-ext")) {
        e.stopPropagation();
        _openSourcePage(s);
        return;
      }
      _evNav.idx = idx;
      _evNavUpdateControls();
      openEvidenceDrawer(s);
    });
    if (idx >= VISIBLE) {
      card.style.display = "none";
      hidden.push(card);
    }
    wrap.appendChild(card);
  });
  if (hidden.length) {
    const pill = document.createElement("button");
    pill.className = "source-more-pill";
    pill.textContent = `+${hidden.length} more`;
    pill.addEventListener("click", () => {
      hidden.forEach(c => { c.style.display = ""; });
      pill.remove();
    });
    wrap.appendChild(pill);
  }
  afterEl.parentNode.insertBefore(outer, afterEl.nextSibling);
  // Don't force-scroll — the user is reading the answer above; only follow if already at bottom
  if (_chatIsNearBottom()) {
    const body = el("chat-body");
    body.scrollTop = body.scrollHeight;
  }
  return outer;
}

// ── Evidence Drawer ──────────────────────────────────────────────────────────

const _evidenceCache = new Map();
const _evNav = { sources: [], idx: 0 };

el("ev-nav-prev").addEventListener("click", () => {
  if (_evNav.idx > 0) { _evNavGo(_evNav.idx - 1); }
});
el("ev-nav-next").addEventListener("click", () => {
  if (_evNav.idx < _evNav.sources.length - 1) { _evNavGo(_evNav.idx + 1); }
});

function _evNavGo(idx) {
  _evNav.idx = idx;
  _evNavUpdateControls();
  // Scroll the strip card into view
  const strip = el("chat-sources");
  if (strip) {
    const cards = strip.querySelectorAll(".source-card");
    const card = cards[idx];
    if (card) {
      card.style.display = "";
      card.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    }
  }
  openEvidenceDrawer(_evNav.sources[idx]);
}

function _evNavUpdateControls() {
  const n = _evNav.sources.length;
  if (n <= 1) { el("ev-nav").style.display = "none"; return; }
  el("ev-nav").style.display = "";
  el("ev-nav-counter").textContent = `${_evNav.idx + 1} / ${n}`;
  el("ev-nav-prev").disabled = _evNav.idx === 0;
  el("ev-nav-next").disabled = _evNav.idx === n - 1;
}

function _openSourcePage(s) {
  if (s.type === "run" && s.run_id) {
    window.open(location.origin + location.pathname + "?run=" + encodeURIComponent(s.run_id) + "&label=" + encodeURIComponent(s.label || s.run_id), "_blank");
  } else if (s.type === "risk") {
    window.open(location.origin + location.pathname + "?tab=risk", "_blank");
  } else {
    window.open(location.origin + location.pathname + "?tab=analysis", "_blank");
  }
}

function openEvidenceDrawer(source) {
  const drawer = el("evidence-drawer");
  drawer.classList.add("open");
  document.body.classList.add("drawer-open");
  // Show loading state while fetching
  el("ev-drawer-name").textContent = source.label || "Evidence";
  el("ev-drawer-badges").innerHTML = "";
  el("ev-drawer-body").innerHTML = `<div class="ev-loading">Loading evidence…</div>`;
  _fetchEvidenceData(source).then(data => renderEvidenceDrawer(data, source)).catch(err => {
    el("ev-drawer-body").innerHTML = `<div class="ev-loading">Could not load evidence.<br><span style="font-size:11px;color:var(--muted)">${escHtml(err.message)}</span></div>`;
  });
}

async function _fetchEvidenceData(source) {
  if (source.type === "test" && source.canonical_name) {
    const cacheKey = "test:" + source.canonical_name + ":" + (source.project || "");
    if (_evidenceCache.has(cacheKey)) return _evidenceCache.get(cacheKey);
    const qs = currentProject ? `?project=${encodeURIComponent(currentProject)}` : "";
    const res = await fetch(`/api/evidence/test/${encodeURIComponent(source.canonical_name)}${qs}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    _evidenceCache.set(cacheKey, data);
    return data;
  }
  if (source.type === "run" && source.run_id) {
    const cacheKey = "run:" + source.run_id + ":" + (source.category || "");
    if (_evidenceCache.has(cacheKey)) return _evidenceCache.get(cacheKey);
    let url = `/api/evidence/run/${encodeURIComponent(source.run_id)}`;
    const params = new URLSearchParams();
    if (source.category)  params.set("category",   source.category);
    if (source.vs_run_id) params.set("vs_run_id", source.vs_run_id);
    if (params.toString()) url += "?" + params.toString();
    const res = await fetch(url);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    _evidenceCache.set(cacheKey, data);
    return data;
  }
  // Fallback for sources without enough identifiers: show card meta inline
  return { type: source.type || "unknown", _fallback: true, label: source.label, meta: source.meta };
}

function _tierBadgeClass(tier) {
  if (!tier) return "default";
  return tier.toLowerCase();
}

function _statusIcon(status) {
  if (status === "passed") return "✅";
  if (status === "skipped") return "⏭";
  return "❌";
}

function renderEvidenceDrawer(data, source) {
  const nameEl = el("ev-drawer-name");
  const badgesEl = el("ev-drawer-badges");
  const bodyEl = el("ev-drawer-body");

  if (data._fallback) {
    nameEl.textContent = data.label || "Evidence";
    badgesEl.innerHTML = "";
    bodyEl.innerHTML = `<div class="ev-loading" style="text-align:left;padding:0"><p style="color:var(--text);font-size:13px">${escHtml(data.meta || "No additional details available.")}</p>
      <div class="ev-actions" style="margin-top:16px">${_makeNavButton(source)}</div></div>`;
    return;
  }

  nameEl.textContent = data.title || source.label || "Evidence";

  // Badges
  let badges = "";
  if (data.risk_tier) {
    badges += `<span class="ev-badge ${_tierBadgeClass(data.risk_tier)}">${escHtml(data.risk_tier)}</span>`;
  }
  if (data.classification) {
    badges += `<span class="ev-badge ${_tierBadgeClass(data.classification)}">${escHtml(data.classification)}</span>`;
  }
  badgesEl.innerHTML = badges;

  let html = "";

  // ── test-level ──
  if (data.type === "test") {
    // Why Relevant
    if (data.why_relevant && data.why_relevant.length) {
      html += `<div><div class="ev-section-title">Why this is relevant</div><ul class="ev-why-list">`;
      data.why_relevant.forEach(w => { html += `<li>${escHtml(w)}</li>`; });
      html += `</ul></div>`;
    }

    // Recent runs
    if (data.recent_runs && data.recent_runs.length) {
      html += `<div><div class="ev-section-title">Recent runs</div><div class="ev-run-list">`;
      data.recent_runs.forEach(r => {
        const icon = _statusIcon(r.status);
        const ts = r.timestamp ? new Date(r.timestamp).toLocaleDateString() : "";
        html += `<div class="ev-run-row">
          <span class="ev-run-status ${escHtml(r.status)}"></span>
          <span>${icon}</span>
          <span class="ev-run-label">${escHtml(r.run_label)}</span>
          <span class="ev-run-status-text" style="color:var(--muted);font-size:11px">${escHtml(r.status)}</span>
          ${ts ? `<span class="ev-run-ts">${escHtml(ts)}</span>` : ""}
        </div>`;
      });
      html += `</div>`;
      if (data.sparkline) {
        html += `<div style="margin-top:6px;font-size:11px;color:var(--muted)">History: <span class="ev-sparkline">${escHtml(data.sparkline)}</span></div>`;
      }
      html += `</div>`;
    }

    // Top failure cause
    if (data.most_frequent_error) {
      const mfe = data.most_frequent_error;
      let freq = "";
      if (mfe.count != null && mfe.total_failures != null) {
        const pct = mfe.total_failures > 0 ? Math.round(mfe.count / mfe.total_failures * 100) : 0;
        freq = `<span style="font-size:11px;color:var(--muted);margin-left:8px">${mfe.count} of ${mfe.total_failures} failure${mfe.total_failures !== 1 ? "s" : ""} · ${pct}%</span>`;
      }
      html += `<div><div class="ev-section-title">Top failure cause</div><div class="ev-error-box">`;
      if (mfe.category) {
        html += `<div class="ev-error-cat">${escHtml(mfe.category)}${freq}</div>`;
      }
      if (mfe.message) {
        html += `<div class="ev-error-msg">${escHtml(mfe.message)}</div>`;
      }
      html += `</div></div>`;
    }

    // Owner
    if (data.owner) {
      html += `<div class="ev-owner-row">Owner: <strong>${escHtml(data.owner)}</strong></div>`;
    }

    // Stats row
    if (data.pass_rate !== undefined) {
      const pct = Math.round(data.pass_rate * 100);
      html += `<div style="font-size:11px;color:var(--muted);display:flex;gap:16px;flex-wrap:wrap">
        <span>Pass rate: <strong style="color:var(--text)">${pct}%</strong></span>
        <span>Runs: <strong style="color:var(--text)">${data.run_count || "—"}</strong></span>
        ${data.flip_score !== undefined ? `<span>Flip score: <strong style="color:var(--text)">${(data.flip_score * 100).toFixed(0)}%</strong></span>` : ""}
      </div>`;
    }
  }

  // ── run-level ──
  if (data.type === "run") {
    const counts = [
      data.passed_count != null ? `✅ ${data.passed_count} passed` : null,
      data.failed_count != null ? `❌ ${data.failed_count} failed` : null,
      data.skipped_count != null ? `⏭ ${data.skipped_count} skipped` : null,
    ].filter(Boolean);
    if (counts.length) {
      html += `<div style="font-size:12px;color:var(--muted);display:flex;gap:12px;flex-wrap:wrap">${counts.map(c=>`<span>${escHtml(c)}</span>`).join("")}</div>`;
    }
    if (data.top_failed && data.top_failed.length) {
      const sectionTitle = data.tests_label || "Top failed tests";
      html += `<div><div class="ev-section-title">${escHtml(sectionTitle)}</div><div class="ev-run-list">`;
      data.top_failed.forEach(t => {
        const icon = t.status === "passed" ? "✅" : "❌";
        html += `<div class="ev-run-row">
          <span class="ev-run-status ${escHtml(t.status || 'failed')}"></span>
          <span>${icon}</span>
          <span class="ev-run-label" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(t.name)}</span>
          ${t.error_type ? `<span style="font-size:10px;color:var(--muted);margin-left:auto">${escHtml(t.error_type)}</span>` : ""}
        </div>`;
        if (t.message) {
          html += `<div style="font-size:11px;color:var(--muted);padding:0 6px 4px 24px;font-family:monospace;word-break:break-word">${escHtml(t.message)}</div>`;
        }
      });
      html += `</div></div>`;
    }
    if (data.recurring_pattern) {
      html += `<div><div class="ev-section-title">Recurring pattern (${data.recurring_pattern.count}x)</div><div class="ev-error-box">`;
      if (data.recurring_pattern.error_type) html += `<div class="ev-error-cat">${escHtml(data.recurring_pattern.error_type)}</div>`;
      if (data.recurring_pattern.message) html += `<div class="ev-error-msg">${escHtml(data.recurring_pattern.message)}</div>`;
      html += `</div></div>`;
    }
  }

  // ── Quick actions ──
  html += `<div class="ev-actions">${_makeNavButton(source, data)}</div>`;

  bodyEl.innerHTML = html;
}

function _makeNavButton(source, data) {
  let btns = "";
  if (data && data.actions) {
    // External URLs (http/https) — open in new tab
    const _navBtn = (url, label) => {
      const safe = _safeUrl(url);
      if (!safe) return "";
      return `<button class="ev-action-btn" onclick="window.open(${JSON.stringify(safe)},'_blank')">${label}</button>`;
    };
    // Internal app URLs (start with /) — navigate in same tab
    const _internalBtn = (url, label) => {
      if (!url || !url.startsWith("/")) return "";
      return `<button class="ev-action-btn" onclick="window.location.href=${escHtml(JSON.stringify(url))}">${label}</button>`;
    };
    btns += _internalBtn(data.actions.run_url,        data.actions.run_label || "Go to this run");
    btns += _internalBtn(data.actions.latest_run_url, "Go to latest run");
    btns += _navBtn(data.actions.history_url,    "Open history ↗");
    btns += _navBtn(data.actions.risk_url,       "Open risk view ↗");
  } else {
    // Fallback — HTML-escape the JSON so `"` chars don't break the onclick attribute
    btns += `<button class="ev-action-btn" onclick="_openSourcePage(${escHtml(JSON.stringify(source))})">Open full page ↗</button>`;
  }
  return btns;
}

// Close drawer
el("ev-close-btn").addEventListener("click", () => {
  el("evidence-drawer").classList.remove("open");
  document.body.classList.remove("drawer-open");
});
// Close on Escape
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && el("evidence-drawer").classList.contains("open")) {
    el("evidence-drawer").classList.remove("open");
    document.body.classList.remove("drawer-open");
  }
});

// ── End Evidence Drawer ──────────────────────────────────────────────────────

function appendChips(afterEl, chips) {
  // Remove any existing chip wrapper first (from prior reply)
  const old = el("chat-chips");
  if (old) old.remove();

  const followups = chips.filter(c => c !== "New conversation");
  const hasNewConv = chips.includes("New conversation");

  const wrapper = document.createElement("div");
  wrapper.className = "chip-wrapper";
  wrapper.id = "chat-chips";

  if (followups.length) {
    const label = document.createElement("span");
    label.className = "chip-label";
    label.textContent = "Follow up";
    wrapper.appendChild(label);

    const row = document.createElement("div");
    row.className = "chip-row";

    followups.forEach(text => {
      const btn = document.createElement("button");
      btn.className = "chip";
      btn.textContent = text;
      btn.addEventListener("click", () => {
        wrapper.remove();
        chatInput.value = text;
        chatInput.dispatchEvent(new Event("input"));
        sendChat();
      });
      row.appendChild(btn);
    });
    wrapper.appendChild(row);
  }

  if (hasNewConv) {
    const btn = document.createElement("button");
    btn.className = "chip chip-new";
    btn.textContent = "New conversation";
    btn.addEventListener("click", () => chatNewConversation());
    wrapper.appendChild(btn);
  }

  afterEl.parentNode.insertBefore(wrapper, afterEl.nextSibling);
  // Only auto-scroll to chips if user is already near the bottom
  if (_chatIsNearBottom()) {
    const body = el("chat-body");
    body.scrollTop = body.scrollHeight;
  }
}

// ── Scroll helpers ──────────────────────────────────────────────────────────

function _chatIsNearBottom() {
  const body = el("chat-body");
  return body.scrollHeight - body.scrollTop - body.clientHeight < 160;
}

function _chatScrollToBottom() {
  const body = el("chat-body");
  body.scrollTo({ top: body.scrollHeight, behavior: "smooth" });
}

// Show/hide the Jump-to-latest FAB
el("chat-body").addEventListener("scroll", () => {
  const btn = el("chat-jump-btn");
  if (btn) btn.classList.toggle("visible", !_chatIsNearBottom());
}, { passive: true });

// ── End scroll helpers ───────────────────────────────────────────────────────

function chatNewConversation() {
  // Option D: show summary card before resetting
  const msgs = el("chat-messages");
  const exchanges = _chat.exchanges;
  const topics = _chat.topics.slice(-3);

  // Build summary card
  const card = document.createElement("div");
  card.className = "chat-summary-card";
  card.innerHTML = `
    <h4>Conversation Summary</h4>
    <div class="sum-row">
      <div class="sum-stat">
        <span class="s-val">${exchanges}</span>
        <span class="s-lbl">Exchanges</span>
      </div>
      <div class="sum-stat">
        <span class="s-val">${topics.length}</span>
        <span class="s-lbl">Topics explored</span>
      </div>
    </div>
    ${topics.length ? `<div class="sum-topics">Topics: ${topics.join(" · ")}</div>` : ""}
  `;
  const body = el("chat-body");
  body.appendChild(card);
  body.scrollTop = body.scrollHeight;

  // After a short pause, reset to welcome screen
  setTimeout(() => {
    // Clear chips
    const chips = el("chat-chips");
    if (chips) chips.remove();
    // Clear messages
    msgs.innerHTML = "";
    msgs.style.display = "none";
    card.remove();
    // Show welcome
    const welcome = el("chat-welcome");
    welcome.style.display = "";
    // Reset state
    _chat.exchanges = 0;
    _chat.topics = [];
    _chat.history = [];
    // Hide new-conversation button
    el("chat-new").style.display = "none";
    // Reset input
    chatInput.value = "";
    chatInput.style.height = "auto";
  }, 2400);
}

// "New conversation" button in the input bar
el("chat-new").addEventListener("click", chatNewConversation);

// Auto-grow textarea
chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px";
});

chatInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) sendChat();
});
chatSend.addEventListener("click", sendChat);

async function sendChat() {
  const q = chatInput.value.trim();
  if (!q) return;
  chatInput.value = "";
  chatInput.style.height = "auto";
  chatSend.disabled = true;
  // Remove chips while waiting
  const oldChips = el("chat-chips");
  if (oldChips) oldChips.remove();
  appendMessage("user", q);
  const thinking = (() => {
    chatShowMessages();
    const div = document.createElement("div");
    div.className = "msg assistant msg-thinking";
    div.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
    el("chat-messages").appendChild(div);
    el("chat-body").scrollTop = el("chat-body").scrollHeight;
    return div;
  })();
  // Send last 6 messages (3 pairs) as history so the LLM has conversation context
  const recentHistory = _chat.history.slice(-6);
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, project: currentProject || null, history: recentHistory })
    });
    const data = await res.json();
    thinking.remove();
    if (!res.ok) {
      appendMessage("system", "⚠ Error: " + (data.detail || res.statusText));
    } else {
      const answerEl = appendMessage("assistant", data.answer);
      const sourcesEl = appendSources(answerEl, data.sources || []);
      appendMessage("system", `Context: ${data.context_mode}`);
      // Record this exchange in history for future turns
      _chat.history.push({ role: "user", content: q });
      _chat.history.push({ role: "assistant", content: data.answer });
      // Update conversation stats
      _chat.exchanges += 1;
      const shortQ = q.length > 40 ? q.slice(0, 40) + "…" : q;
      _chat.topics.push(shortQ);
      // Show "New conversation" button after first exchange
      el("chat-new").style.display = "";
      // Append dynamic follow-up chips from the API response
      const chipSet = data.follow_ups && data.follow_ups.length ? data.follow_ups : [];
      appendChips(sourcesEl || answerEl, [...chipSet, "New conversation"]);
    }
  } catch(e) {
    thinking.remove();
    appendMessage("system", "⚠ Network error: " + e.message);
  } finally {
    chatSend.disabled = false;
    chatInput.focus();
  }
}

// ── Run detail ──
let _allTestsCache = [];

el("runs-body").addEventListener("click", e => {
  const row = e.target.closest("tr.run-row");
  if (!row) return;
  const seq = row.cells[0]?.textContent?.trim() || "?";
  const fmtDate2 = row.cells[3]?.textContent?.trim() || "";
  const fmt2 = row.cells[2]?.textContent?.trim() || "";
  const label = `Run ${seq} \u00b7 ${fmt2} \u00b7 ${fmtDate2}`;
  showRunDetail(row.dataset.runId, label);
});

el("back-to-runs").addEventListener("click", () => {
  el("runs-detail-view").style.display = "none";
  el("runs-list-view").style.display = "";
});

document.querySelectorAll(".filter-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const status = btn.dataset.status;
    renderTests(status ? _allTestsCache.filter(t => {
      if (status === "failed") return t.status === "failed" || t.status === "broken";
      return t.status === status;
    }) : _allTestsCache);
  });
});

async function showRunDetail(runId, label) {
  _allTestsCache = [];
  el("runs-list-view").style.display = "none";
  el("runs-detail-view").style.display = "";
  el("run-detail-title").textContent = label;
  el("run-detail-stats").innerHTML = "";
  el("run-incidents-wrap").style.display = "none";
  el("run-incidents-cards").innerHTML = "";
  el("tests-body").innerHTML = `<tr><td colspan="6" class="loading">Loading tests\u2026</td></tr>`;
  document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
  document.querySelector(".filter-btn[data-status='']").classList.add("active");
  try {
    const [tests, incidents] = await Promise.all([
      apiFetch(`/api/runs/${runId}/tests`),
      apiFetch(`/api/runs/${runId}/incidents`).catch(() => []),
    ]);
    _allTestsCache = tests;
    const total = tests.length;
    const passed = tests.filter(t => t.status === "passed").length;
    const failed = tests.filter(t => t.status === "failed" || t.status === "broken").length;
    const skipped = tests.filter(t => t.status === "skipped").length;
    const incidentCount = incidents ? incidents.length : 0;
    const incidentImpact = incidents ? incidents.reduce((s, i) => s + i.impacted_test_count, 0) : 0;
    const incidentCardHtml = incidentCount > 0
      ? `<div class="stat-card" style="min-width:160px">
           <div class="label">Incidents</div>
           <div class="value" style="color:var(--fail)">${fmt(incidentCount)}</div>
           <div style="font-size:11px;color:var(--muted);margin-top:2px">${fmt(incidentImpact)} test${incidentImpact !== 1 ? 's' : ''} affected</div>
         </div>`
      : `<div class="stat-card"><div class="label">Incidents</div><div class="value" style="color:var(--pass)">0</div></div>`;
    el("run-detail-stats").innerHTML = `
      <div class="stat-card"><div class="label">Total</div><div class="value">${fmt(total)}</div></div>
      <div class="stat-card"><div class="label">Passed</div><div class="value pass">${fmt(passed)}</div></div>
      ${incidentCardHtml}
      <div class="stat-card"><div class="label">Failed</div><div class="value fail">${fmt(failed)}</div></div>
      <div class="stat-card"><div class="label">Skipped</div><div class="value skip">${fmt(skipped)}</div></div>
    `;
    if (incidentCount) {
      el("run-incidents-wrap").style.display = "";
      el("run-incidents-cards").innerHTML = renderIncidentCards(incidents);
      _bindIncidentToggles(el("run-incidents-cards"));
    }
    renderTests(tests);
  } catch(e) {
    el("tests-body").innerHTML = `<tr><td colspan="6" class="error-msg">${e.message}</td></tr>`;
  }
}

function renderTests(tests) {
  const tbody = el("tests-body");
  if (!tests.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">No tests found.</td></tr>`;
    return;
  }
  const rows = [];
  tests.forEach((t, i) => {
    const badgeType = t.status === "passed" ? "pass"
      : t.status === "broken" ? "broken"
      : t.status === "failed" ? "fail"
      : t.status === "skipped" ? "skip" : "skip";
    const detailId = "tc-detail-" + i;
    const hasDetail = !!(t.stack_trace || t.message || (t.attachments && t.attachments.length) || t.status === "failed" || t.status === "broken");
    const icon = hasDetail
      ? `<span class="expand-icon" style="color:var(--accent);margin-right:8px;font-size:11px">&#9654;</span>`
      : `<span style="display:inline-block;width:20px"></span>`;
    rows.push(`<tr class="${hasDetail ? "tc-row" : ""}" onclick="toggleTc('${detailId}')">
      <td style="max-width:340px;word-break:break-word">${icon}${escHtml(t.name)}</td>
      <td>${badge(badgeType, t.status)}</td>
      <td style="font-size:12px;color:var(--muted)">${escHtml(t.suite ?? "\u2014")}</td>
      <td style="font-size:12px;color:var(--muted)">${t.owner ? escHtml(t.owner) : "\u2014"}</td>
      <td>${fmtMs(t.duration_ms)}</td>
      <td style="font-size:12px;max-width:240px;word-break:break-word;color:var(--muted)">${escHtml(truncate(t.message ?? "", 80))}</td>
    </tr>`);
    if (hasDetail) {
      const metaParts = [];
      if (t.error_type) metaParts.push(`<div><div class="meta-label">Error Type</div><div class="meta-value" style="color:var(--fail)">${escHtml(t.error_type)}</div></div>`);
      if (t.failed_step) metaParts.push(`<div><div class="meta-label">Failed Step</div><div class="meta-value">${escHtml(t.failed_step)}</div></div>`);
      if (t.feature) metaParts.push(`<div><div class="meta-label">Feature</div><div class="meta-value">${escHtml(t.feature)}</div></div>`);
      if (t.story) metaParts.push(`<div><div class="meta-label">Story</div><div class="meta-value">${escHtml(t.story)}</div></div>`);
      if (t.owner) metaParts.push(`<div><div class="meta-label">Owner</div><div class="meta-value">${escHtml(t.owner)}</div></div>`);
      const metaHtml = metaParts.length
        ? `<div class="meta-grid" style="margin-bottom:14px">${metaParts.join("")}</div>` : "";
      const msgHtml = t.message
        ? `<div class="meta-label" style="margin-bottom:4px">Full Message</div><pre class="stack" style="max-height:120px">${escHtml(t.message)}</pre>` : "";
      const stackHtml = t.stack_trace
        ? `<div class="meta-label" style="margin-top:12px;margin-bottom:4px">Stack Trace</div><pre class="stack">${escHtml(t.stack_trace)}</pre>`
        : (t.status === "failed" || t.status === "broken")
          ? `<div class="meta-label" style="margin-top:12px;margin-bottom:4px">Stack Trace</div><span style="color:var(--muted);font-size:12px">No stack trace was present in the report.</span>`
          : "";
      const noDetailHtml = !t.message && !t.stack_trace && !(t.attachments && t.attachments.filter(a => a.resolved_path).length)
        ? `<span style="color:var(--muted);font-size:12px;display:block;margin-top:8px">No failure details extracted. Re-ingest with <code>--force</code> to refresh.</span>` : "";
      let attHtml = "";
      if (t.attachments && t.attachments.length) {
        // Only render attachments that have a resolved path on disk; skip nulls to avoid broken images.
        const serveable = t.attachments.filter(a => a.resolved_path);
        if (serveable.length) {
          const attItems = serveable.map(a => {
            const origIdx = t.attachments.indexOf(a);
            const isImg = a.kind === "screenshot" || (a.name && /[.](png|jpg|jpeg|gif|webp|bmp)$/i.test(a.name));
            const url = `/api/tests/${encodeURIComponent(t.tc_id)}/attachment/${origIdx}`;
            if (isImg) return `<a href="${url}" target="_blank"><img class="tc-screenshot" src="${url}" alt="${escHtml(a.name ?? "screenshot")}" loading="lazy" /></a>`;
            return `<div class="att-item"><span class="badge badge-skip" style="font-size:10px">${a.kind ?? "file"}</span> ${escHtml(a.name ?? "attachment")}</div>`;
          }).join("");
          attHtml = `<div class="meta-label" style="margin-top:12px;margin-bottom:6px">Attachments (${serveable.length})</div><div class="att-grid">${attItems}</div>`;
        }
      }
      rows.push(`<tr class="tc-detail hidden" id="${detailId}">
        <td colspan="5" style="padding:16px 14px 16px 32px;background:var(--surface2);border-top:1px solid var(--border)">${metaHtml}${msgHtml}${stackHtml}${attHtml}${noDetailHtml}</td>
      </tr>`);
    }
  });
  tbody.innerHTML = rows.join("");
}

function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Returns url only if it has an http/https scheme; null otherwise.
// Prevents javascript:, data:, and other dangerous URL schemes from
// being set on href attributes or embedded in onclick handlers.
function _safeUrl(url) {
  if (!url) return null;
  try {
    const u = new URL(String(url));
    return (u.protocol === "http:" || u.protocol === "https:") ? String(url) : null;
  } catch { return null; }
}

// ── Markdown renderer via marked.js (CDN) ──
function renderMarkdown(raw) {
  if (typeof marked === "undefined") return escHtml(raw).replace(/\\n/g, "<br>");
  // Prevent setext-style heading promotion.  In Markdown, a '---' or '==='
  // line that directly follows a non-blank line promotes that line to <h2>/<h1>
  // (setext syntax).  LLM output uses '---' purely as a visual separator, so
  // insert a blank line before any such line to force it to render as <hr>.
  const safe = raw
    .replace(/([^\\n])\\n([ \\t]*-{3,}[ \\t]*$)/gm, "$1\\n\\n$2")
    .replace(/([^\\n])\\n([ \\t]*={3,}[ \\t]*$)/gm, "$1\\n\\n$2");
  let html = marked.parse(safe, { breaks: true, gfm: true });
  // Sanitize marked output before writing to innerHTML.
  // Applied before the emoji replacements so our trusted dot spans aren't stripped.
  if (typeof DOMPurify !== "undefined") {
    html = DOMPurify.sanitize(html, { ADD_ATTR: ["target"] });
  }
  // Post-process: replace leading emoji markers with subtle colored dots
  // (applied after sanitization — these spans are generated by us, not from user input)
  const _dot = (c) => `<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--${c});margin-right:6px;vertical-align:middle"></span>`;
  html = html.replace(/🔴|❌|⚠️/g, _dot("fail"));
  html = html.replace(/🟢|✅/g, _dot("pass"));
  html = html.replace(/🟡|🟠/g, _dot("skip"));
  html = html.replace(/🔵|ℹ️/g, _dot("accent"));
  return html;
}

function toggleTc(id) {
  const row = el(id);
  if (!row) return;
  row.classList.toggle("hidden");
  const prev = row.previousElementSibling;
  if (prev) {
    const icon = prev.querySelector(".expand-icon");
    if (icon) icon.innerHTML = row.classList.contains("hidden") ? "&#9654;" : "&#9660;";
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// ── Compare panel ──
// ─────────────────────────────────────────────────────────────────────────────

const _cmp = {
  // currently loaded comparison result
  result: null,
  // run IDs included in the current view, in column order (oldest first)
  runIds: [],
  // oldest run_sequence in current view (for "add more" pagination)
  oldestRunId: null,
  // current cell preview mode: status | category | fingerprint | owner
  previewMode: "status",
  // pending custom-selection set (tc_id strings)
  customPicked: new Set(),
  // cached per-row health by canonical_name for the drawer
  rowHealthCache: {},
  // number of runs in the current window (used for Health tooltip)
  windowSize: 0,
};

// ── Inject run-picker modal into DOM once ──
(function() {
  const overlay = document.createElement("div");
  overlay.id = "run-picker-overlay";
  overlay.className = "modal-overlay hidden";
  overlay.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <span>Select Runs to Compare</span>
        <button class="drawer-close" onclick="cmpCloseModal()">&#10005;</button>
      </div>
      <div class="modal-body" id="run-picker-body">Loading\u2026</div>
      <div class="modal-footer">
        <button class="btn" style="background:var(--surface2);color:var(--text);border:1px solid var(--border)" onclick="cmpCloseModal()">Cancel</button>
        <button class="btn" id="run-picker-confirm">Compare Selected</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  // Inject detail drawer
  const drawer = document.createElement("div");
  drawer.id = "test-drawer";
  drawer.className = "drawer";
  drawer.innerHTML = `
    <div class="drawer-header">
      <strong id="drawer-title" style="font-size:14px">Test Details</strong>
      <button class="drawer-close" onclick="cmpCloseDrawer()">&#10005;</button>
    </div>
    <div class="drawer-body" id="drawer-body"></div>`;
  document.body.appendChild(drawer);
})();

el("run-picker-confirm").addEventListener("click", () => {
  const checked = [...document.querySelectorAll(".run-picker-row input:checked")].map(c => c.value);
  if (!checked.length) return;
  cmpCloseModal();
  cmpLoadCustom(checked);
});

// ── Preset buttons ──
document.querySelectorAll(".cmp-preset").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".cmp-preset").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const p = btn.dataset.preset;
    if (p === "5")                cmpLoadWindow(5);
    else if (p === "10")          cmpLoadWindow(10);
    else if (p === "latest_vs_prev") cmpLoadWindow(2);
    else if (p === "custom")      cmpOpenModal();
  });
});

// ── Preview mode ──
document.querySelectorAll(".preview-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".preview-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    _cmp.previewMode = btn.dataset.preview;
    if (_cmp.result) cmpRenderMatrix();
  });
});

// ── Add older runs ──
el("cmp-add-more").addEventListener("click", () => {
  if (!_cmp.oldestRunId) return;
  cmpLoadWindow(5, _cmp.oldestRunId, /*append=*/true);
});

// ── Compare filter: live search ──
el("cmp-search").addEventListener("input", () => {
  if (_cmp.result) cmpRenderMatrix();
});

// ── Core loaders ──
async function cmpLoadWindow(limit, beforeRunId, append=false) {
  cmpSetLoading();
  const qs = currentProject ? `?project=${encodeURIComponent(currentProject)}&limit=${limit}` : `?limit=${limit}`;
  const full = beforeRunId ? qs + `&before_run_id=${encodeURIComponent(beforeRunId)}` : qs;
  try {
    const res = await apiFetch("/api/compare/history" + full);
    if (append && _cmp.result) {
      // Merge new (older) runs to the LEFT of existing
      const newRunIds = res.runs.map(r => r.run_id);
      const mergedRowMap = {};
      for (const row of _cmp.result.rows) {
        mergedRowMap[row.canonical_name] = row;
      }
      for (const row of res.rows) {
        if (mergedRowMap[row.canonical_name]) {
          // Prepend cells from older runs
          mergedRowMap[row.canonical_name].cells = [...row.cells, ...mergedRowMap[row.canonical_name].cells];
        } else {
          // New test not seen in original window – pad right with absent
          const padded = row.cells.concat(
            _cmp.result.runs.map(r => ({run_id: r.run_id, state:"absent", fingerprint:null,
              error_type:null, message:null, root_cause_category:null,
              is_latest_change:false, tooltip:"ABSENT"}))
          );
          mergedRowMap[row.canonical_name] = {...row, cells: padded};
        }
      }
      const mergedRuns = [...res.runs, ..._cmp.result.runs];
      _cmp.result = {
        ..._cmp.result,
        runs: mergedRuns,
        rows: Object.values(mergedRowMap),
        facets: res.facets,  // refresh facets
      };
    } else {
      _cmp.result = res;
    }
    cmpAfterLoad();
  } catch(e) {
    cmpShowError(e.message);
  }
}

async function cmpLoadCustom(runIds) {
  cmpSetLoading();
  try {
    const res = await fetch("/api/compare/custom", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({run_ids: runIds, filters: {}})
    });
    if (!res.ok) throw new Error((await res.json().catch(()=>({}))).detail || res.statusText);
    _cmp.result = await res.json();
    cmpAfterLoad();
  } catch(e) {
    cmpShowError(e.message);
  }
}

function cmpAfterLoad() {
  const r = _cmp.result;
  if (!r || !r.runs.length) {
    el("cmp-info").textContent = "No runs found for the selected project / window.";
    el("cmp-info").style.display = "";
    el("cmp-matrix-wrap").style.display = "none";
    el("cmp-summary-cards").innerHTML = "";
    return;
  }
  // Track oldest run for "add more"
  _cmp.oldestRunId = r.runs[0]?.run_id || null;
  // Build health cache
  _cmp.rowHealthCache = {};
  _cmp.windowSize = r.runs.length;
  for (const row of r.rows) {
    _cmp.rowHealthCache[row.canonical_name] = row.health;
  }
  // Render
  cmpRenderSummary(r.summary);
  cmpPopulateFacets(r.facets, r.report_format);
  cmpRenderMatrix();
  el("cmp-info").style.display = "none";
  el("cmp-matrix-wrap").style.display = "";
  el("cmp-matrix-title").textContent = `History Matrix — ${r.runs.length} run${r.runs.length!==1?"s":""} · ${r.summary.unique_tests} tests`;
}

function cmpSetLoading() {
  el("cmp-info").textContent = "Loading comparison\u2026";
  el("cmp-info").style.display = "";
  el("cmp-matrix-wrap").style.display = "none";
  el("cmp-summary-cards").innerHTML = "";
}

function cmpShowError(msg) {
  el("cmp-info").innerHTML = `<span class="error-msg">${escHtml(msg)}</span>`;
  el("cmp-info").style.display = "";
}

// ── Summary cards ──
function cmpRenderSummary(s) {
  const cards = [
    { key: "runs",        label: "Runs",         value: fmt(s.window_size),         cls: "" },
    { key: "tests",       label: "Tests",        value: fmt(s.unique_tests),         cls: "" },
    { key: "flaky",       label: "Flaky",        value: fmt(s.flaky_tests),          cls: "flaky" },
    { key: "broken",      label: "Broken",       value: fmt(s.consistently_broken),  cls: "fail" },
    { key: "new_failures",label: "New Failures", value: fmt(s.new_failures_latest),  cls: "fail" },
    { key: "fixed",       label: "Fixed",        value: fmt(s.fixed_latest),         cls: "pass" },
    { key: "stable",      label: "Stable",       value: fmt(s.stable_tests),         cls: "pass", small: true },
  ];
  el("cmp-summary-cards").innerHTML = cards.map(c =>
    `<div class="stat-card cmp-card-clickable" data-cmp-card="${c.key}" title="Click to see details">
      <div class="label">${c.label}</div>
      <div class="value ${c.cls}"${c.small ? ' style="font-size:20px"' : ''}>${c.value}</div>
    </div>`
  ).join("");
  el("cmp-summary-cards").querySelectorAll(".cmp-card-clickable").forEach(card => {
    card.addEventListener("click", () => openCmpInsightDrawer(card.dataset.cmpCard));
  });
}

// ── Compare Insight Drawer ────────────────────────────────────────────────────

el("cmp-insight-close").addEventListener("click", () => closeCmpInsightDrawer());
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeCmpInsightDrawer();
});

function closeCmpInsightDrawer() {
  el("cmp-insight-drawer").classList.remove("open");
}

function openCmpInsightDrawer(cardKey) {
  const r = _cmp.result;
  if (!r) return;
  const drawer = el("cmp-insight-drawer");
  const titleEl = el("cmp-insight-title");
  const bodyEl = el("cmp-insight-body");
  drawer.classList.add("open");

  const runs = r.runs;           // newest-last order (index 0 = oldest)
  const rows = r.rows;
  const latestIdx = runs.length - 1;

  function _stateOf(row) {
    const c = row.cells[latestIdx];
    return c ? c.state : "absent";
  }
  function _isFailed(state) { return state === "failed" || state === "broken"; }
  function _dotCls(state) {
    if (state === "passed") return "pass";
    if (_isFailed(state)) return "fail";
    if (state === "flaky") return "flaky";
    return "muted";
  }
  function _statusIcon(state) {
    if (state === "passed") return "✓";
    if (_isFailed(state)) return "✗";
    if (state === "skipped") return "—";
    return "·";
  }

  let html = "";

  if (cardKey === "runs") {
    titleEl.textContent = `Runs in window (${runs.length})`;
    html = runs.slice().reverse().map(run => {
      const label = run.run_sequence ? `Run #${run.run_sequence}` : run.run_id.slice(0, 8);
      const date = run.started_at ? new Date(run.started_at * 1000).toLocaleDateString() : "";
      const branch = run.branch ? `<span class="cmp-insight-meta">${escHtml(run.branch)}</span>` : "";
      return `<div class="cmp-insight-run-row">
        <div class="cmp-insight-run-label">${escHtml(label)}</div>
        ${branch}
        ${date ? `<span class="cmp-insight-run-meta">${escHtml(date)}</span>` : ""}
      </div>`;
    }).join("");
    if (!html) html = `<div class="ev-loading">No runs loaded.</div>`;

  } else if (cardKey === "tests") {
    titleEl.textContent = `All tests (${rows.length})`;
    html = rows.map(row => {
      const state = _stateOf(row);
      return `<div class="cmp-insight-row">
        <div class="cmp-insight-dot ${_dotCls(state)}"></div>
        <div class="cmp-insight-name" title="${escHtml(row.display_name)}">${escHtml(row.display_name)}</div>
        <div class="cmp-insight-meta">${escHtml(state)}</div>
      </div>`;
    }).join("");
    if (!html) html = `<div class="ev-loading">No tests found.</div>`;

  } else if (cardKey === "flaky") {
    const flaky = rows.filter(row => row.health && row.health.classification === "flaky");
    titleEl.textContent = `Flaky tests (${flaky.length})`;
    html = flaky.map(row => {
      const state = _stateOf(row);
      return `<div class="cmp-insight-row">
        <div class="cmp-insight-dot flaky"></div>
        <div class="cmp-insight-name" title="${escHtml(row.display_name)}">${escHtml(row.display_name)}</div>
        <div class="cmp-insight-meta">latest: ${escHtml(state)}</div>
      </div>`;
    }).join("");
    if (!html) html = `<div class="ev-loading">No flaky tests in this window.</div>`;

  } else if (cardKey === "broken") {
    const broken = rows.filter(row => row.health && row.health.classification === "consistently_broken");
    titleEl.textContent = `Consistently broken (${broken.length})`;
    html = broken.map(row => {
      const cell = row.cells[latestIdx];
      const errType = cell && cell.error_type ? cell.error_type : "";
      return `<div class="cmp-insight-row">
        <div class="cmp-insight-dot fail"></div>
        <div class="cmp-insight-name" title="${escHtml(row.display_name)}">${escHtml(row.display_name)}</div>
        ${errType ? `<div class="cmp-insight-meta">${escHtml(errType)}</div>` : ""}
      </div>`;
    }).join("");
    if (!html) html = `<div class="ev-loading">No consistently broken tests.</div>`;

  } else if (cardKey === "new_failures") {
    const newFails = rows.filter(row => {
      const cell = row.cells[latestIdx];
      return cell && _isFailed(cell.state) && cell.is_latest_change;
    });
    titleEl.textContent = `New failures in latest run (${newFails.length})`;
    html = newFails.map(row => {
      const cell = row.cells[latestIdx];
      const errType = cell && cell.error_type ? cell.error_type : "";
      const cat = cell && cell.root_cause_category ? cell.root_cause_category : "";
      return `<div class="cmp-insight-row">
        <div class="cmp-insight-dot fail"></div>
        <div class="cmp-insight-name" title="${escHtml(row.display_name)}">${escHtml(row.display_name)}</div>
        <div class="cmp-insight-meta">${escHtml(errType || cat || cell.state)}</div>
      </div>`;
    }).join("");
    if (!html) html = `<div class="ev-loading">No new failures in the latest run.</div>`;

  } else if (cardKey === "fixed") {
    const fixed = rows.filter(row => {
      const cell = row.cells[latestIdx];
      return cell && cell.state === "passed" && cell.is_latest_change;
    });
    titleEl.textContent = `Fixed in latest run (${fixed.length})`;
    html = fixed.map(row => {
      // Show what it failed with in the previous run
      const prevCell = row.cells[latestIdx - 1];
      const prevErr = prevCell && prevCell.error_type ? prevCell.error_type : (prevCell ? prevCell.state : "");
      return `<div class="cmp-insight-row">
        <div class="cmp-insight-dot pass"></div>
        <div class="cmp-insight-name" title="${escHtml(row.display_name)}">${escHtml(row.display_name)}</div>
        ${prevErr ? `<div class="cmp-insight-meta">was: ${escHtml(prevErr)}</div>` : ""}
      </div>`;
    }).join("");
    if (!html) html = `<div class="ev-loading">No tests fixed in the latest run.</div>`;

  } else if (cardKey === "stable") {
    const stable = rows.filter(row => row.health && row.health.classification === "stable");
    titleEl.textContent = `Stable tests (${stable.length})`;
    html = stable.map(row => `
      <div class="cmp-insight-row">
        <div class="cmp-insight-dot pass"></div>
        <div class="cmp-insight-name" title="${escHtml(row.display_name)}">${escHtml(row.display_name)}</div>
      </div>`).join("");
    if (!html) html = `<div class="ev-loading">No stable tests found.</div>`;
  }

  bodyEl.innerHTML = html;
  drawer.scrollTop = 0;
}

// ── End Compare Insight Drawer ────────────────────────────────────────────────

// ══════════════════════════════════════════════════════════════════════════════
// Compare Filter System (cmpf) — modern popover selectors + active chips
// ══════════════════════════════════════════════════════════════════════════════

const _cmpf = {
  owner: "", suite: "", feature: "", module: "", statusFilter: "",
  _facets: { owners: [], suites: [], features: [], modules: [] },
  _openPop: null,
};

const _CMPF_STATUS_OPTS = [
  { value: "flaky_only",         label: "Flaky" },
  { value: "broken_only",        label: "Consistently broken" },
  { value: "latest_failed_only", label: "Failed in latest run" },
  { value: "changed_only",       label: "Changed in latest run" },
];

function cmpfTogglePop(key) {
  const wasOpen = _cmpf._openPop === key;
  cmpfCloseAllPops();
  if (!wasOpen) {
    _cmpf._openPop = key;
    const pop = el("cmpf-pop-" + key);
    const btn = el("cmpf-btn-" + key);
    if (pop) pop.style.display = "";
    if (btn) btn.classList.add("open");
    // Populate list, then focus search field if present
    cmpfRenderPopList(key, "");
    const s = el("cmpf-psearch-" + key);
    if (s) { s.value = ""; requestAnimationFrame(() => s.focus()); }
  }
}

function cmpfCloseAllPops() {
  ["owner","suite","feature","module","status"].forEach(k => {
    const pop = el("cmpf-pop-" + k);
    const btn = el("cmpf-btn-" + k);
    if (pop) pop.style.display = "none";
    if (btn) btn.classList.remove("open");
  });
  _cmpf._openPop = null;
}

// Close popovers on outside click
document.addEventListener("click", e => {
  if (_cmpf._openPop && !e.target.closest(".cmpf-trig-wrap")) {
    cmpfCloseAllPops();
  }
});

function cmpfRenderPopList(key, query) {
  const list = el("cmpf-list-" + key);
  if (!list) return;
  const q = (query || "").toLowerCase();

  if (key === "status") {
    const opts = _CMPF_STATUS_OPTS.filter(o => !q || o.label.toLowerCase().includes(q));
    if (!opts.length) { list.innerHTML = `<div class="cmpf-pop-none">No options</div>`; return; }
    list.innerHTML = opts.map(o => {
      const sel = _cmpf.statusFilter === o.value;
      return `<div class="cmpf-pop-item${sel ? " selected" : ""}" onclick="cmpfSelect('status','${o.value}')">
        <span class="cmpf-pop-item-label">${escHtml(o.label)}</span>
        ${sel ? `<span class="cmpf-check">✓</span>` : ""}
      </div>`;
    }).join("");
  } else {
    const items = (_cmpf._facets[key + "s"] || _cmpf._facets[key] || []).filter(v => !q || v.toLowerCase().includes(q));
    if (!items.length) { list.innerHTML = `<div class="cmpf-pop-none">No options</div>`; return; }
    const cur = _cmpf[key];
    list.innerHTML = items.map(v => {
      const sel = cur === v;
      return `<div class="cmpf-pop-item${sel ? " selected" : ""}" onclick="cmpfSelect('${key}','${escHtml(v).replace(/'/g,'&#39;')}')">
        <span class="cmpf-pop-item-label">${escHtml(v)}</span>
        ${sel ? `<span class="cmpf-check">✓</span>` : ""}
      </div>`;
    }).join("");
  }
}

function cmpfFilterPopList(key, query) {
  cmpfRenderPopList(key, query);
}

function cmpfSelect(key, value) {
  if (key === "status") {
    _cmpf.statusFilter = _cmpf.statusFilter === value ? "" : value;
  } else {
    _cmpf[key] = _cmpf[key] === value ? "" : value;
  }
  cmpfCloseAllPops();
  cmpfSyncUI();
  if (_cmp.result) cmpRenderMatrix();
}

function cmpfClear(key) {
  if (key === "status") _cmpf.statusFilter = "";
  else _cmpf[key] = "";
  cmpfSyncUI();
  if (_cmp.result) cmpRenderMatrix();
}

function cmpfClearAll() {
  _cmpf.owner = _cmpf.suite = _cmpf.feature = _cmpf.module = _cmpf.statusFilter = "";
  const search = el("cmp-search");
  if (search) search.value = "";
  cmpfSyncUI();
  if (_cmp.result) cmpRenderMatrix();
}

// Update trigger button labels + active state, then render chips
function cmpfSyncUI() {
  const MAP = {
    owner:  { key: "owner",  val: () => _cmpf.owner },
    suite:  { key: "suite",  val: () => _cmpf.suite },
    feature:{ key: "feature",val: () => _cmpf.feature },
    module: { key: "module", val: () => _cmpf.module },
    status: { key: "status", val: () => _cmpf.statusFilter },
  };
  for (const [k, cfg] of Object.entries(MAP)) {
    const btn = el("cmpf-btn-" + k);
    if (!btn) continue;
    const v = cfg.val();
    btn.classList.toggle("active", v !== "");
    // Label: show selected value inline (truncated) or just field name
    let label = k.charAt(0).toUpperCase() + k.slice(1);
    if (v) {
      const display = k === "status"
        ? (_CMPF_STATUS_OPTS.find(o => o.value === v) || {}).label || v
        : v;
      const short = display.length > 15 ? display.slice(0, 14) + "\u2026" : display;
      label = `<span style="color:var(--muted);font-weight:400">${label}</span>: ${escHtml(short)}`;
    }
    btn.innerHTML = `${label} <span class="cmpf-caret">\u25be</span>`;
  }
  cmpfRenderChips();
}

function cmpfRenderChips() {
  const row = el("cmpf-chips-row");
  if (!row) return;
  const chips = [];
  if (_cmpf.owner)       chips.push({ key: "owner",   label: "Owner",   value: _cmpf.owner });
  if (_cmpf.suite)       chips.push({ key: "suite",   label: "Suite",   value: _cmpf.suite });
  if (_cmpf.feature)     chips.push({ key: "feature", label: "Feature", value: _cmpf.feature });
  if (_cmpf.module)      chips.push({ key: "module",  label: "Module",  value: _cmpf.module });
  if (_cmpf.statusFilter) {
    const opt = _CMPF_STATUS_OPTS.find(o => o.value === _cmpf.statusFilter);
    chips.push({ key: "status", label: "Status", value: opt ? opt.label : _cmpf.statusFilter });
  }
  if (!chips.length) { row.style.display = "none"; row.innerHTML = ""; return; }
  row.style.display = "flex";
  row.innerHTML = chips.map(c =>
    `<span class="cmpf-chip">
      <span class="cmpf-chip-label">${escHtml(c.label)}:</span>
      <span class="cmpf-chip-value" title="${escHtml(c.value)}">${escHtml(c.value)}</span>
      <button class="cmpf-chip-x" onclick="cmpfClear('${c.key}')" title="Remove">&#x2715;</button>
    </span>`
  ).join("") + (chips.length > 1
    ? `<button class="cmpf-clear-all" onclick="cmpfClearAll()">Clear all</button>` : "");
}

// ── Populate facet data (called after load) ──
function cmpPopulateFacets(facets, reportFormat) {
  const isExtent = reportFormat === "extent";
  const sw = el("cmpf-trig-suite-wrap"),   fw = el("cmpf-trig-feature-wrap"),
        mw = el("cmpf-trig-module-wrap");
  if (sw) sw.style.display = isExtent ? "none" : "";
  if (fw) fw.style.display = isExtent ? "none" : "";
  if (mw) mw.style.display = isExtent ? "" : "none";

  _cmpf._facets.owners   = facets.owners   || [];
  _cmpf._facets.suites   = facets.suites   || [];
  _cmpf._facets.features = facets.features || [];
  _cmpf._facets.modules  = facets.modules  || [];

  // Clear stale filter values not present in new facets
  if (_cmpf.owner   && !_cmpf._facets.owners.includes(_cmpf.owner))     _cmpf.owner = "";
  if (_cmpf.suite   && !_cmpf._facets.suites.includes(_cmpf.suite))     _cmpf.suite = "";
  if (_cmpf.feature && !_cmpf._facets.features.includes(_cmpf.feature)) _cmpf.feature = "";
  if (_cmpf.module  && !_cmpf._facets.modules.includes(_cmpf.module))   _cmpf.module = "";
  cmpfSyncUI();
}

// ── Collect active filters (used by cmpRenderMatrix) ──
function cmpActiveFilters() {
  return {
    search:       el("cmp-search").value.trim().toLowerCase(),
    suite:        _cmpf.suite,
    owner:        _cmpf.owner,
    feature:      _cmpf.feature,
    module:       _cmpf.module,
    statusFilter: _cmpf.statusFilter,
  };
}

// ── Matrix render ──
function cmpRenderMatrix() {
  if (!_cmp.result) return;
  const { runs, rows } = _cmp.result;
  const f = cmpActiveFilters();
  const preview = _cmp.previewMode;

  // Apply client-side filters
  let filtered = rows;
  if (f.search) filtered = filtered.filter(r => r.display_name.toLowerCase().includes(f.search));
  if (f.suite) filtered = filtered.filter(r => r.suite === f.suite);
  if (f.owner) filtered = filtered.filter(r => r.owner === f.owner);
  if (f.feature) filtered = filtered.filter(r => r.feature === f.feature);
  if (f.module) filtered = filtered.filter(r => (r.tags || []).includes(f.module));
  if (f.statusFilter === "flaky_only") filtered = filtered.filter(r => r.health.classification === "flaky");
  if (f.statusFilter === "broken_only") filtered = filtered.filter(r => r.health.classification === "consistently_broken");
  if (f.statusFilter === "latest_failed_only") filtered = filtered.filter(r => {
    const last = r.cells[r.cells.length-1];
    return last && (last.state === "failed" || last.state === "broken");
  });
  if (f.statusFilter === "changed_only") filtered = filtered.filter(r => {
    const last = r.cells[r.cells.length-1];
    return last?.is_latest_change;
  });

  // Thead
  const thead = el("cmp-thead");
  thead.innerHTML = `<tr>
    <th class="row-hdr">Test</th>
    ${runs.map(run => `
      <th class="run-col-hdr">
        ${escHtml(run.display_name)}
        <span class="rdate">${fmtDate(run.started_at)}</span>
        ${run.branch ? `<span class="rdate" style="color:var(--accent)">${escHtml(run.branch)}</span>` : ""}
      </th>`).join("")}
    <th id="cmp-health-th" style="padding:8px 10px;font-size:11px;color:var(--muted);cursor:help" data-tooltip="">
      Health
    </th>
  </tr>`;

  // Update Health column tooltip with live window size
  const _n = _cmp.windowSize;
  const _exPct = _n > 0 ? Math.round(1 / _n * 100) : 0;
  const _runWord = _n !== 1 ? "s are" : " is";
  const _healthTh = el("cmp-health-th");
  if (_healthTh) {
    _healthTh.dataset.tooltip = "Shows how often this test passed in the runs displayed here. Example: if the last " + _n + " run" + _runWord + " shown and the test passed once, the health is " + _exPct + "%.";
  }

  // Tbody — virtualise: only render first 500 rows immediately
  const LIMIT = 500;
  const visible = filtered.slice(0, LIMIT);
  const tbody = el("cmp-tbody");
  tbody.innerHTML = visible.map(row => {
    const cellsHtml = runs.map((run, ci) => {
      const cell = row.cells.find(c => c.run_id === run.run_id) ||
        {state:"absent",fingerprint:null,error_type:null,message:null,root_cause_category:null,is_latest_change:false,tooltip:"ABSENT"};
      const stateCls = `mc-${cell.state}`;
      const changeCls = cell.is_latest_change ? " mc-change" : "";
      let inner = "";
      if (preview === "status") {
        const icons = {passed:"✓",failed:"✗",broken:"✗",skipped:"—",absent:"·"};
        inner = icons[cell.state] || cell.state[0].toUpperCase();
      } else if (preview === "category") {
        inner = cell.root_cause_category ? cell.root_cause_category.replace("_"," ").slice(0,8) : (cell.state === "absent" ? "·" : "—");
      } else if (preview === "fingerprint") {
        inner = cell.fingerprint ? cell.fingerprint.slice(0,8) : (cell.state === "absent" ? "·" : "—");
      } else if (preview === "owner") {
        inner = row.owner ? row.owner.slice(0,8) : "—";
      }
      return `<td title="${escHtml(cell.tooltip)}">
        <div class="mc ${stateCls}${changeCls}" onclick="cmpCellClick(event,'${escHtml(row.canonical_name)}','${run.run_id}')">${escHtml(String(inner))}</div>
      </td>`;
    }).join("");

    const hcls = `hb-${row.health.classification}`;
    const hLabel = row.health.classification.replace("_"," ");
    const passRatePct = (row.health.pass_rate * 100).toFixed(0) + "%";

    return `<tr>
      <td class="row-hdr" onclick="cmpRowClick('${escHtml(row.canonical_name)}')" style="cursor:pointer">
        <span title="${escHtml(row.display_name)}">${escHtml(truncate(row.display_name, 40))}</span>
        <span class="hbadge ${hcls}">${hLabel}</span>
      </td>
      ${cellsHtml}
      <td style="padding:6px 10px;text-align:center;white-space:nowrap">
        <span style="font-size:12px;color:var(--pass)">${passRatePct}</span>
      </td>
    </tr>`;
  }).join("");

  if (filtered.length > LIMIT) {
    const extra = document.createElement("tr");
    extra.innerHTML = `<td colspan="${runs.length+2}" class="empty">\u2026 ${filtered.length - LIMIT} more rows hidden. Narrow your filters.</td>`;
    tbody.appendChild(extra);
  } else if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="${runs.length+2}" class="empty">No tests match the current filters.</td></tr>`;
  }
}

// ── Cell & row click → Detail Drawer ──
function cmpCellClick(evt, canonicalName, runId) {
  evt.stopPropagation();
  cmpOpenDrawer(canonicalName, runId);
}

function cmpRowClick(canonicalName) {
  cmpOpenDrawer(canonicalName, null);
}

function cmpOpenDrawer(canonicalName, runId) {
  const row = _cmp.result?.rows.find(r => r.canonical_name === canonicalName);
  if (!row) return;

  el("drawer-title").textContent = truncate(row.display_name, 48);
  const health = row.health;
  const hcls = `hb-${health.classification}`;

  // Find the specific cell if runId given
  const cell = runId ? row.cells.find(c => c.run_id === runId) : null;
  const runLabel = runId
    ? (_cmp.result.runs.find(r => r.run_id === runId)?.display_name || runId)
    : null;

  const sparkline = row.cells.map(c => {
    const sym = {passed:"✓",failed:"✗",broken:"✗",skipped:"—",absent:"·"};
    const col = {passed:"var(--pass)",failed:"var(--fail)",broken:"#fb923c",skipped:"var(--skip)",absent:"var(--border)"};
    return `<span style="color:${col[c.state]||"var(--muted)"}">${sym[c.state]||"?"}</span>`;
  }).join("<span style='letter-spacing:1px'></span>");

  let cellDetailHtml = "";
  if (cell && cell.state !== "absent") {
    cellDetailHtml = `
      <div class="drawer-section">
        <div class="drawer-section-title">Selected Cell — ${escHtml(runLabel || "")}</div>
        <div class="meta-grid">
          <div><div class="meta-label">Status</div><div class="meta-value">${escHtml(cell.state)}</div></div>
          ${cell.error_type ? `<div><div class="meta-label">Error Type</div><div class="meta-value" style="color:var(--fail)">${escHtml(cell.error_type.split(".").pop())}</div></div>` : ""}
          ${cell.root_cause_category ? `<div><div class="meta-label">Category</div><div class="meta-value">${escHtml(cell.root_cause_category.replace("_"," "))}</div></div>` : ""}
          ${cell.fingerprint ? `<div><div class="meta-label">Fingerprint</div><div class="meta-value mono">${escHtml(cell.fingerprint.slice(0,16))}</div></div>` : ""}
        </div>
        ${cell.message ? `<div class="meta-label" style="margin-top:10px;margin-bottom:4px">Message</div><pre class="stack" style="max-height:100px">${escHtml(cell.message)}</pre>` : ""}
      </div>`;
  }

  el("drawer-body").innerHTML = `
    <div class="drawer-section">
      <div class="drawer-section-title">Test Identity</div>
      <div class="meta-grid">
        ${row.suite ? `<div><div class="meta-label">Suite</div><div class="meta-value">${escHtml(row.suite)}</div></div>` : ""}
        ${row.feature ? `<div><div class="meta-label">Feature</div><div class="meta-value">${escHtml(row.feature)}</div></div>` : ""}
        ${row.owner ? `<div><div class="meta-label">Owner</div><div class="meta-value">${escHtml(row.owner)}</div></div>` : ""}
      </div>
    </div>
    <div class="drawer-section">
      <div class="drawer-section-title">Health (this window)</div>
      <div class="meta-grid">
        <div><div class="meta-label">Classification</div>
          <div class="meta-value"><span class="hbadge ${hcls}">${health.classification.replace("_"," ")}</span></div></div>
        <div><div class="meta-label">Pass Rate</div><div class="meta-value" style="color:var(--pass)">${(health.pass_rate*100).toFixed(0)}%</div></div>
        <div><div class="meta-label">Flip Score</div><div class="meta-value" style="color:var(--flaky)">${health.flip_score.toFixed(2)}</div></div>
      </div>
    </div>
    <div class="drawer-section">
      <div class="drawer-section-title">Run History</div>
      <div style="font-family:monospace;font-size:16px;letter-spacing:4px;padding:4px 0">${sparkline}</div>
      <div style="font-size:11px;color:var(--muted);margin-top:4px">Oldest left → Newest right</div>
    </div>
    ${cellDetailHtml}
  `;

  el("test-drawer").classList.add("open");
}

function cmpCloseDrawer() {
  el("test-drawer").classList.remove("open");
}

// ── Run picker modal ──
async function cmpOpenModal() {
  const overlay = el("run-picker-overlay");
  overlay.classList.remove("hidden");
  const body = el("run-picker-body");
  body.innerHTML = "Loading\u2026";
  try {
    const qs = currentProject ? `?project=${encodeURIComponent(currentProject)}&limit=50` : "?limit=50";
    const runs = await apiFetch("/api/compare/runs" + qs);
    if (!runs.length) {
      body.innerHTML = `<div class="empty">No runs found for this project.</div>`;
      return;
    }
    body.innerHTML = runs.map(r => {
      const alreadyIn = _cmp.result?.runs.some(ex => ex.run_id === r.run_id);
      const np = r.passed_count || 0;
      const nf = r.failed_count || 0;
      return `<label class="run-picker-row">
        <input type="checkbox" value="${escHtml(r.run_id)}" ${alreadyIn ? "checked" : ""}>
        <span style="font-weight:600;min-width:60px">${escHtml(r.display_name)}</span>
        <span style="color:var(--muted);font-size:12px">${fmtDate(r.started_at)}</span>
        ${r.branch ? `<span class="badge badge-skip" style="font-size:10px">${escHtml(r.branch)}</span>` : ""}
        <span style="color:var(--pass);font-size:12px;margin-left:auto">${np}\u2713</span>
        <span style="color:var(--fail);font-size:12px">${nf}\u2717</span>
      </label>`;
    }).join("");
  } catch(e) {
    body.innerHTML = `<div class="error-msg">${escHtml(e.message)}</div>`;
  }
}

function cmpCloseModal() {
  el("run-picker-overlay").classList.add("hidden");
}

// Close modal on overlay click
el("run-picker-overlay").addEventListener("click", e => {
  if (e.target === el("run-picker-overlay")) cmpCloseModal();
});

// Close drawer on Escape
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    cmpCloseDrawer();
    cmpCloseModal();
  }
});

// \u2500\u2500 Incidents panel \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

const _SEV_LABEL = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };
const _CONF_LABEL = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };

const _IC = {
  copy: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`,
  check: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  chevron: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>`,
};

function _incCopyToClip(btn, text) {
  navigator.clipboard.writeText(text).then(() => {
    btn.classList.add("copied");
    const prev = btn.innerHTML;
    btn.innerHTML = _IC.check;
    setTimeout(() => { btn.classList.remove("copied"); btn.innerHTML = prev; }, 1800);
  }).catch(() => {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    btn.classList.add("copied");
    setTimeout(() => btn.classList.remove("copied"), 1800);
  });
}

// Delegated handler for any button with data-copy attribute
document.addEventListener("click", function(e) {
  const btn = e.target.closest("[data-copy]");
  if (btn) _incCopyToClip(btn, btn.getAttribute("data-copy"));
});

/**
 * Turn raw evidence strings into human-readable insight bullets.
 * Extracts inline code for signatures / exceptions.
 */
function _evidenceToInsights(evidenceList) {
  return (evidenceList || []).map(e => {
    // Wrap backtick-quoted values in <code>
    let html = escHtml(e).replace(/`([^`]+)`/g, '<code>$1</code>');
    return html;
  });
}

/**
 * Split a recommended-action string into individual steps.
 * If the string already has numbered lines ("1. …") use those;
 * otherwise split on sentence boundaries (period + space).
 */
function _actionToSteps(action) {
  if (!action) return [];
  // Try numbered patterns first: "1. step" or "1) step"
  const numbered = action.match(/\\d+[.)][^\\d]+/g);
  if (numbered && numbered.length > 1) {
    return numbered.map(s => s.replace(/^\\d+[.)\\s]+/, '').trim()).filter(Boolean);
  }
  // Try semicolon-separated
  if (action.includes(';')) {
    const parts = action.split(';').map(s => s.trim()).filter(s => s.length > 3);
    if (parts.length > 1) return parts;
  }
  // Try sentence splitting (period + space)
  const sentences = action.split(/(?<=\\.)\\s+/).filter(s => s.trim().length > 3);
  if (sentences.length > 1) return sentences;
  // Try splitting on connectors: ", then ", ", and ", ", also "
  const connectors = action.split(/,\\s*(?:then|and then|also|next)\\s+/i).map(s => s.trim()).filter(s => s.length > 3);
  if (connectors.length > 1) return connectors;
  // Single step
  return sentences.length ? sentences : [action];
}

function renderIncidentCards(incidents) {
  if (!incidents || !incidents.length) {
    return `<div class="incidents-empty">&#10003; No incidents detected \u2014 all failures are isolated or none exist.</div>`;
  }
  return incidents.map((inc, idx) => {
    const sevCls = `sev-${inc.severity}`;
    const sigHtml = inc.signature
      ? `<span class="incident-sig">&#35;${inc.signature.slice(0,8)}</span>` : "";
    const bodyId = `inc-body-${idx}`;
    const testsId = `inc-tests-${idx}`;

    // ── Inline metadata line ──
    const metaParts = [];
    metaParts.push(`${inc.impacted_test_count} test${inc.impacted_test_count !== 1 ? 's' : ''} affected`);
    if (inc.root_cause_category) metaParts.push(escHtml(inc.root_cause_category));
    if (inc.confidence) metaParts.push(`<span class="conf-${inc.confidence}">${_CONF_LABEL[inc.confidence] || inc.confidence}</span>`);
    const metaHtml = `<div class="inc-meta">${metaParts.join('<span class="inc-meta-sep">&middot;</span>')}</div>`;

    // ── Hero root cause ──
    const heroHtml = `<div class="inc-hero">${escHtml(inc.probable_root_cause)}</div>`;

    // ── Evidence → insight bullets ──
    const insights = _evidenceToInsights(inc.evidence);
    const insightsHtml = insights.length ? `
      <div class="inc-heading">Why this is happening</div>
      <ul class="inc-insights">${insights.map(h => `<li>${h}</li>`).join('')}</ul>` : "";

    // ── Affected areas (component tags) ──
    const areasHtml = (inc.components || []).length ? `
      <div class="inc-heading">Affected areas</div>
      <div class="inc-areas">${inc.components.map(c => `<span class="inc-area">${escHtml(c)}</span>`).join('')}</div>` : "";

    // ── What to do next (numbered steps) ──
    const steps = _actionToSteps(inc.recommended_action);
    const stepsHtml = steps.length ? `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
        <div class="inc-heading" style="margin-bottom:0">What to do next</div>
        <button class="inc-ghost-btn" data-copy="${escHtml(inc.recommended_action || '')}">
          ${_IC.copy} Copy
        </button>
      </div>
      <ol class="inc-steps">${steps.map(s => `<li>${escHtml(s)}</li>`).join('')}</ol>` : "";

    // ── Impacted tests ──
    const testsListHtml = (inc.impacted_tests || []).map(n => `<li>${escHtml(n)}</li>`).join("");
    const testsSection = `
      <div class="inc-tests-section">
        <button class="inc-tests-toggle" id="btn-${testsId}"
          onclick="toggleIncidentTests2('${testsId}', 'btn-${testsId}', ${inc.impacted_test_count})">
          ${_IC.chevron}
          <span>Show ${inc.impacted_test_count} impacted test${inc.impacted_test_count !== 1 ? "s" : ""}</span>
        </button>
        <ul class="inc-tests-list" id="${testsId}" style="display:none">${testsListHtml}</ul>
      </div>`;

    // ── Stack trace (if present) ──
    const stackHtml = inc.representative_stack_trace ? `
      <div class="inc-stack-section">
        <div class="inc-stack-hdr">
          <span class="inc-heading" style="margin:0">Stack trace</span>
          <button class="inc-ghost-btn" data-copy="${escHtml(inc.representative_stack_trace)}">
            ${_IC.copy} Copy
          </button>
        </div>
        <pre class="stack" style="max-height:220px;overflow:auto;margin-top:6px">${escHtml(inc.representative_stack_trace)}</pre>
      </div>` : "";

    // ── Assemble card ──
    return `
<div class="incident-card">
  <div class="incident-card-hdr" onclick="toggleIncidentBody(this)">
    <div class="incident-card-hdr-left">
      <span class="badge ${sevCls}">${_SEV_LABEL[inc.severity] || inc.severity}</span>
      <span class="incident-title">${escHtml(inc.title)}${sigHtml}</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <span class="incident-impact">${inc.impacted_test_count} test${inc.impacted_test_count !== 1 ? "s" : ""} affected</span>
      <span class="incident-chevron">&#9654;</span>
    </div>
  </div>
  <div class="incident-card-body" id="${bodyId}">
    <div class="inc-body-inner">
      ${metaHtml}
      ${heroHtml}
      ${insightsHtml}
      ${areasHtml}
      ${stepsHtml}
      ${testsSection}
      ${stackHtml}
    </div>
  </div>
</div>`.trim();
  }).join("");
}

function toggleIncidentBody(hdrEl) {
  const card = hdrEl.closest(".incident-card");
  if (!card) return;
  card.classList.toggle("open");
}

function toggleIncidentTests(listId, btnId, count) {
  const list = el(listId);
  const btn  = el(btnId);
  if (!list) return;
  const showing = list.style.display !== "none";
  list.style.display = showing ? "none" : "";
  if (btn) btn.innerHTML = showing
    ? `&#9654; Show ${count} impacted test${count !== 1 ? "s" : ""}`
    : `&#9660; Hide impacted tests`;
}

function toggleIncidentTests2(listId, btnId, count) {
  const list = el(listId);
  const btn  = el(btnId);
  if (!list) return;
  const showing = list.style.display !== "none";
  list.style.display = showing ? "none" : "";
  if (btn) {
    btn.classList.toggle("open", !showing);
    const label = showing
      ? `Show ${count} impacted test${count !== 1 ? "s" : ""}`
      : `Hide impacted tests`;
    btn.querySelector("span").textContent = label;
  }
}

function _bindIncidentToggles(_container) {
  // No-op: onclick handlers are inline. Reserved for future event delegation.
}

let _incidentsRunId = null;

async function loadIncidents() {
  const sel    = el("incidents-run-select");
  const cards  = el("incidents-cards");
  const stats  = el("incidents-stats");

  if (!_runsData.length) await loadRuns();
  const runs = _runsData;

  sel.innerHTML = `<option value="">Select a run\u2026</option>` +
    runs.map(r => {
      const lbl = `#${r.run_sequence ?? "?"} ${r.project ?? ""} \u2014 ${fmtDate(r.started_at)}`;
      return `<option value="${r.run_id}">${escHtml(lbl)}</option>`;
    }).join("");

  if (runs.length && !_incidentsRunId) {
    sel.value = runs[0].run_id;
    _incidentsRunId = runs[0].run_id;
  } else if (_incidentsRunId) {
    sel.value = _incidentsRunId;
  }

  sel.onchange = async () => {
    _incidentsRunId = sel.value;
    await _fetchAndRenderIncidents(_incidentsRunId, cards, stats);
  };

  if (_incidentsRunId) {
    await _fetchAndRenderIncidents(_incidentsRunId, cards, stats);
  } else {
    cards.innerHTML = `<div class="incidents-empty">Select a run above to see detected incidents.</div>`;
    stats.innerHTML = "";
  }
}

async function _fetchAndRenderIncidents(runId, cards, stats) {
  if (!runId) { cards.innerHTML = ""; stats.innerHTML = ""; return; }
  cards.innerHTML = `<div class="loading">Loading incidents\u2026</div>`;
  stats.innerHTML = "";
  try {
    const incidents = await apiFetch(`/api/runs/${runId}/incidents`);
    const total      = incidents.length;
    const critical   = incidents.filter(i => i.severity === "critical").length;
    const high       = incidents.filter(i => i.severity === "high").length;
    const medium     = incidents.filter(i => i.severity === "medium").length;
    const low        = incidents.filter(i => i.severity === "low").length;
    const totalTests = incidents.reduce((s, i) => s + i.impacted_test_count, 0);
    stats.innerHTML = `
      <div class="stat-card"><div class="label">Incidents</div><div class="value">${fmt(total)}</div></div>
      <div class="stat-card"><div class="label">Tests Affected</div><div class="value fail">${fmt(totalTests)}</div></div>
      ${critical ? `<div class="stat-card"><div class="label">Critical</div><div class="value" style="color:#f87171">${critical}</div></div>` : ""}
      ${high     ? `<div class="stat-card"><div class="label">High</div><div class="value" style="color:#fb923c">${high}</div></div>`     : ""}
      ${medium   ? `<div class="stat-card"><div class="label">Medium</div><div class="value" style="color:#f59e0b">${medium}</div></div>`  : ""}
      ${low      ? `<div class="stat-card"><div class="label">Low</div><div class="value pass">${low}</div></div>`                       : ""}
    `;
    cards.innerHTML = renderIncidentCards(incidents);
  } catch(e) {
    cards.innerHTML = `<div class="incidents-empty error-msg">Failed to load incidents: ${escHtml(e.message)}</div>`;
  }
}

// Load compare panel when its tab is activated
document.querySelectorAll(".tab").forEach(tab => {
  if (tab.dataset.tab === "compare") {
    tab.addEventListener("click", () => {
      if (!_cmp.result && currentProject !== undefined) {
        cmpLoadWindow(5);
      }
    });
  }
});

// ─────────────────────────────────────────────────────────────────────────────

// ── Theme toggle ──
(function() {
  const toggle = el("theme-toggle");
  const root = document.documentElement;
  const saved = localStorage.getItem("ari-theme") || "dark";
  function applyTheme(t) {
    root.setAttribute("data-theme", t);
    toggle.checked = (t === "dark");
    localStorage.setItem("ari-theme", t);
  }
  applyTheme(saved);
  toggle.addEventListener("click", () => {
    applyTheme(toggle.checked ? "dark" : "light");
  });
})();

// ── Sidebar collapse ──
(function() {
  const sidebar = document.getElementById("sidebar");
  const btn = document.getElementById("sidebar-collapse-btn");
  if (!sidebar || !btn) return;
  const KEY = "ari-sidebar-collapsed";
  if (localStorage.getItem(KEY) === "true") {
    sidebar.classList.add("collapsed");
    document.body.classList.add("sidebar-collapsed");
  }
  btn.addEventListener("click", () => {
    const collapsed = sidebar.classList.toggle("collapsed");
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    localStorage.setItem(KEY, collapsed);
  });
})();

// ── Mobile sidebar ──
(function() {
  const sidebar = document.getElementById("sidebar");
  const overlay = document.getElementById("sidebar-overlay");
  const hamburger = document.getElementById("mobile-menu-btn");
  if (!sidebar) return;
  function closeSidebar() {
    sidebar.classList.remove("mobile-open");
    overlay && overlay.classList.remove("visible");
  }
  hamburger && hamburger.addEventListener("click", () => {
    const open = sidebar.classList.toggle("mobile-open");
    overlay && overlay.classList.toggle("visible", open);
  });
  overlay && overlay.addEventListener("click", closeSidebar);
})();

// ── Bootstrap ──
// Check for deep-link params (?run=<id> or ?tab=<name>) placed by source card clicks
(async function bootstrap() {
  await loadProjects();  // sets up project selector + loads runs/analysis
  const params = new URLSearchParams(location.search);
  const runId = params.get("run");
  const tabName = params.get("tab");
  const highlight = params.get("highlight");
  if (runId) {
    // Navigate to Runs tab and open the specific run detail
    switchTab("runs");
    // Wait for loadRuns to finish rendering, then open detail
    await new Promise(r => setTimeout(r, 600));
    const label = params.get("label") || runId;
    showRunDetail(runId, label);
    // Clean up URL to avoid re-triggering on refresh
    history.replaceState(null, "", "/?tab=runs");
  } else if (tabName) {
    switchTab(tabName);
    // If navigating to risk tab with a highlight target, scroll + flash the row
    if (tabName === "risk" && highlight) {
      // Wait for loadRisk() to finish populating the table
      await new Promise(r => setTimeout(r, 800));
      const row = el("risk-body").querySelector(`tr[data-canonical="${CSS.escape(highlight)}"]`);
      if (row) {
        row.scrollIntoView({ behavior: "smooth", block: "center" });
        row.classList.add("risk-row-highlight");
        row.addEventListener("animationend", () => row.classList.remove("risk-row-highlight"), { once: true });
      }
      history.replaceState(null, "", "/?tab=risk");
    }
  }
})();