function observeValue(value, fallback = '—') {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'number') return value.toLocaleString();
  return String(value);
}

function observeKvRows(rows) {
  return Object.entries(rows || {}).map(([key, value]) => `
    <div class="observe-kv-row"><span>${escapeHtml(key)}</span><b>${escapeHtml(observeValue(value))}</b></div>
  `).join('') || '<div class="muted small-text">No data available.</div>';
}

function renderObserveStatus(status) {
  const el = document.getElementById('observeStatusCards');
  if (!el) return;
  const logging = status?.logging || {};
  const rotation = logging.rotation || {};
  const files = logging.files || {};
  const select = document.getElementById('observeLogName');
  if (select && !select.dataset.enhanced) {
    select.innerHTML = `
      <option value="controller">Controller</option>
      <option value="audit">Audit</option>
      <option value="wrapper">Wrapper</option>
      <option value="pi-agent">pi.dev runtime</option>
      <option value="pacctl">pacctl</option>`;
    select.dataset.enhanced = 'true';
  }
  const store = status?.store || {};
  el.classList.remove('muted');
  el.innerHTML = `
    <article class="observe-status-card">
      <span>Logging backend</span>
      <b>${escapeHtml(logging.backend || 'local logging')}</b>
      <small>${logging.configured ? 'configured' : 'not configured yet'}</small>
    </article>
    <article class="observe-status-card">
      <span>Rotation</span>
      <b>${escapeHtml(observeValue(rotation.max_bytes))} bytes</b>
      <small>${escapeHtml(observeValue(rotation.backup_count))} retained files</small>
    </article>
    <article class="observe-status-card">
      <span>Controller log</span>
      <b>${escapeHtml(observeValue(files.controller?.size_bytes, '0'))} bytes</b>
      <small>${escapeHtml(files.controller?.path || '')}</small>
    </article>
    <article class="observe-status-card">
      <span>Audit log</span>
      <b>${escapeHtml(observeValue(files.audit?.size_bytes, '0'))} bytes</b>
      <small>${escapeHtml(files.audit?.path || '')}</small>
    </article>
    <article class="observe-status-card">
      <span>pi.dev runtime log</span>
      <b>${escapeHtml(observeValue(files.pi_agent?.size_bytes, '0'))} bytes</b>
      <small>${escapeHtml(files.pi_agent?.path || '')}</small>
    </article>
    <article class="observe-status-card">
      <span>pacctl log</span>
      <b>${escapeHtml(observeValue(files.pacctl?.size_bytes, '0'))} bytes</b>
      <small>${escapeHtml(files.pacctl?.path || '')}</small>
    </article>
    <article class="observe-status-card">
      <span>Embedded store</span>
      <b>${escapeHtml(observeValue(store.size_bytes, '0'))} bytes</b>
      <small>${escapeHtml(store.path || store.backend || '')}</small>
    </article>
  `;
  const runtime = document.getElementById('observeRuntime');
  if (runtime) {
    runtime.classList.remove('muted');
    runtime.innerHTML = observeKvRows({
      'Python': status?.runtime?.python,
      'Platform': status?.runtime?.platform,
      'PID': status?.runtime?.pid,
      'Level': logging.level,
      'Log directory': logging.log_dir,
    });
  }
}

function renderObserveMetrics(metrics) {
  const el = document.getElementById('observeMetrics');
  if (!el) return;
  el.classList.remove('muted');
  el.innerHTML = observeKvRows({
    'Sessions': metrics?.sessions?.total ?? metrics?.session_count,
    'Running tasks': metrics?.tasks?.running ?? metrics?.task_status?.running,
    'Completed tasks': metrics?.tasks?.completed ?? metrics?.task_status?.completed,
    'Failed tasks': metrics?.tasks?.failed ?? metrics?.task_status?.failed,
    'Endpoints': metrics?.endpoints?.total ?? metrics?.endpoint_count,
    'Alerts': metrics?.alerts?.length ?? metrics?.alert_count,
  });
}

function renderObserveModelUsage(usage) {
  const el = document.getElementById('observeModelUsage');
  if (!el) return;
  const summary = usage?.summary || usage || {};
  el.classList.remove('muted');
  el.innerHTML = observeKvRows({
    'Calls': summary.calls ?? summary.total_calls,
    'Prompt tokens': summary.prompt_tokens ?? summary.input_tokens,
    'Completion tokens': summary.completion_tokens ?? summary.output_tokens,
    'Total tokens': summary.total_tokens,
    'Estimated tokens': summary.estimated_tokens,
    'Failures': summary.failures ?? summary.failed_calls,
  });
}

function renderObserveEmbeddedMetrics(data) {
  const el = document.getElementById('observeEmbeddedMetrics');
  if (!el) return;
  const rows = Array.isArray(data?.summary) ? data.summary : [];
  el.classList.remove('muted');
  if (!rows.length) {
    el.innerHTML = '<div class="muted small-text">No embedded metric samples yet. Use the UI briefly and refresh.</div>';
    return;
  }
  el.innerHTML = rows.slice(0, 8).map((row) => `
    <div class="observe-kv-row"><span>${escapeHtml(row.name || 'metric')}<small>${escapeHtml(row.component || '')}</small></span><b>${escapeHtml(observeValue(row.samples))} samples · avg ${escapeHtml(observeValue(Math.round(Number(row.avg_value || 0))))}</b></div>
  `).join('');
}

function renderObserveTraces(data) {
  const el = document.getElementById('observeTraces');
  if (!el) return;
  const spans = Array.isArray(data?.spans) ? data.spans : [];
  el.classList.remove('muted');
  if (!spans.length) {
    el.innerHTML = '<div class="muted small-text">No trace spans yet. Requests and selected operations will appear here.</div>';
    return;
  }
  el.innerHTML = spans.slice(0, 20).map((span) => {
    const attrs = span.attributes || {};
    const status = String(span.status || 'ok');
    return `<article class="observe-trace-row ${status === 'error' ? 'danger' : ''}">
      <div><b>${escapeHtml(span.operation || 'operation')}</b><small>${escapeHtml(span.component || '')} · ${escapeHtml(span.start_ts || '')}</small></div>
      <span>${escapeHtml(observeValue(Math.round(Number(span.duration_ms || 0))))} ms</span>
      <small>${escapeHtml(attrs.method || '')} ${escapeHtml(attrs.path || '')}</small>
    </article>`;
  }).join('');
}

async function loadObserveLogs() {
  const pre = document.getElementById('observeLogTail');
  const select = document.getElementById('observeLogName');
  if (!pre) return;
  if (window.PACLoading) PACLoading.set(pre, 'Loading log tail…'); else pre.textContent = 'Loading log tail…';
  pre.classList.add('muted');
  try {
    const name = select?.value || 'controller';
    const data = await api(`/v1/system/logs/tail?name=${encodeURIComponent(name)}&limit=12000`);
    pre.classList.remove('muted');
    pre.textContent = data?.content || 'No log entries yet.';
  } catch (e) {
    pre.textContent = `Could not load log tail: ${e.message}`;
  }
}

async function loadObservePanel() {
  const cards = document.getElementById('observeStatusCards');
  if (cards) { if (window.PACLoading) PACLoading.set(cards, 'Loading observability status…'); else cards.textContent = 'Loading observability status…'; }
  const [status, metrics, usage, embeddedMetrics, traces] = await Promise.all([
    api('/v1/system/observability').catch((e) => ({error: e.message})),
    api('/v1/metrics/summary').catch((e) => ({error: e.message})),
    api('/v1/model-usage?since_hours=24').catch((e) => ({error: e.message})),
    api('/v1/observability/metrics?since_hours=24&limit=120').catch((e) => ({error: e.message})),
    api('/v1/observability/traces?since_hours=24&limit=40').catch((e) => ({error: e.message})),
  ]);
  if (status?.error) {
    if (cards) cards.innerHTML = `<div class="muted">Could not load observability status: ${escapeHtml(status.error)}</div>`;
  } else {
    renderObserveStatus(status);
  }
  if (metrics?.error) {
    const el = document.getElementById('observeMetrics');
    if (el) el.textContent = `Could not load metrics: ${metrics.error}`;
  } else renderObserveMetrics(metrics);
  if (usage?.error) {
    const el = document.getElementById('observeModelUsage');
    if (el) el.textContent = `Could not load model usage: ${usage.error}`;
  } else renderObserveModelUsage(usage);
  if (embeddedMetrics?.error) {
    const el = document.getElementById('observeEmbeddedMetrics');
    if (el) el.textContent = `Could not load embedded metrics: ${embeddedMetrics.error}`;
  } else renderObserveEmbeddedMetrics(embeddedMetrics);
  if (traces?.error) {
    const el = document.getElementById('observeTraces');
    if (el) el.textContent = `Could not load traces: ${traces.error}`;
  } else renderObserveTraces(traces);
  await loadObserveLogs();
}

function setupObservePanel() {
  const refresh = document.getElementById('observeRefresh');
  if (refresh) refresh.onclick = () => loadObservePanel().catch(() => {});
  const refreshLogs = document.getElementById('observeRefreshLogs');
  if (refreshLogs) refreshLogs.onclick = () => loadObserveLogs().catch(() => {});
  const select = document.getElementById('observeLogName');
  if (select) select.onchange = () => loadObserveLogs().catch(() => {});
  const openEvents = document.getElementById('observeOpenEvents');
  if (openEvents) openEvents.onclick = () => {
    const navButton = document.querySelector('[data-shell-route="events"]');
    if (navButton) {
      navButton.click();
      return;
    }
    if (typeof activateTab === 'function') activateTab('events-tab');
  };
  const prune = document.getElementById('observePruneStore');
  if (prune) prune.onclick = async () => {
    prune.disabled = true;
    try { await api('/v1/observability/prune', {method:'POST'}); await loadObservePanel(); }
    catch (e) { alert(`Could not prune observability store: ${e.message || String(e)}`); }
    finally { prune.disabled = false; }
  };
}

document.addEventListener('DOMContentLoaded', setupObservePanel);
