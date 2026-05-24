// Session sidebar rendering for workspace/context aware sessions.
function renderSessionSidebar(sessions = window.__pacSessions || []) {
  const list = document.getElementById('sessionSidebarList');
  if (!list) return;
  if (!sessions.length) {
    list.innerHTML = '<div class="muted">No sessions yet.</div>';
    return;
  }
  list.innerHTML = '';
  sessions.slice().reverse().forEach((s) => {
    const contextName = String(s?.metadata?.agent_context_name || '').trim();
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `session-sidebar-item${selectedSession?.id === s.id ? ' active' : ''}`;
    item.innerHTML = `<strong>${escapeHtml(s.name || s.id)}</strong><div class="session-sidebar-meta">${escapeHtml(s.agent_profile || '-')} · ${escapeHtml(s.model || '-')} · ${escapeHtml(s.permission_profile || '-')}</div>${contextName ? `<div class="session-sidebar-meta">${escapeHtml(contextName)}</div>` : ''}<div class="session-sidebar-meta">${escapeHtml(s.workspace_path || '')}</div>`;
    const del = document.createElement('button');
    del.className = 'session-delete-btn';
    del.title = 'Delete session';
    del.textContent = '×';
    del.onclick = async (ev) => {
      ev.stopPropagation();
      ev.preventDefault();
      if (!confirm(`Delete session '${s.name || s.id}'?`)) return;
      const r = await api(`/v1/sessions/${s.id}`, {method:'DELETE', body: JSON.stringify({remove_workspace: false})});
      if (r?.ok) {
        if (selectedSession?.id === s.id) {
          selectedSession = null;
          activeSessionTaskId = null;
          resetSessionTimelineState?.();
          const timeline = document.getElementById('sessionTimeline');
          if (timeline) timeline.innerHTML = '<div class="muted">Select a session from the sidebar to inspect its timeline.</div>';
          const title = document.getElementById('sessionTitle');
          if (title) title.textContent = 'Select a session';
          const lockEl = document.getElementById('sessionEndpointLock');
          if (lockEl) lockEl.textContent = '';
          const summaryEl = document.getElementById('selectedSession');
          if (summaryEl) summaryEl.innerHTML = '';
        }
        await loadSessions().catch(()=>{});
      } else {
        alert(r?.error || 'Delete failed');
      }
    };
    item.appendChild(del);
    item.onclick = () => { switchToTab('sessions-tab'); selectSession(s.id); };
    list.appendChild(item);
  });
}
