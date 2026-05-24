// Combined access-request and task approval list rendering

async function loadApprovals() {
  if (approvalsRequest) return approvalsRequest;
  approvalsRequest = (async () => {
    const [tasks, accessRequests] = await Promise.all([
      api('/v1/tasks/pending-approvals'),
      api('/v1/access-requests').catch(() => []),
    ]);
    const targets = [document.getElementById('approvals'), document.getElementById('approvalsSettings')].filter(Boolean);
    targets.forEach((el) => {
      el.innerHTML = '';
      accessRequests.forEach((req) => {
        const row=document.createElement('div'); row.className='row';
        row.innerHTML=`<div><b>${escapeHtml(req.username || req.user_id)}</b><br><span class="muted">${escapeHtml(`${req.access} ${req.resource_type} ${req.resource_id}`)}</span>${req.reason ? `<br><span class="muted">${escapeHtml(req.reason)}</span>` : ''}</div>`;
        const a=document.createElement('button'); a.textContent='Grant access'; a.onclick=async()=>{await api(`/v1/access-requests/${encodeURIComponent(req.id)}/approve`, {method:'POST'}); await fetchAuthStatus(); renderAuthInfo(); await loadApprovals(); await loadUsersList().catch(()=>{});};
        const r=document.createElement('button'); r.textContent='Reject'; r.onclick=async()=>{await api(`/v1/access-requests/${encodeURIComponent(req.id)}/reject`, {method:'POST'}); await fetchAuthStatus(); renderAuthInfo(); await loadApprovals();};
        row.append(a,r); el.appendChild(row);
      });
      tasks.forEach((t) => {
        const row=document.createElement('div'); row.className='row';
        row.innerHTML=`<div><b>${t.command || t.prompt}</b><br><span class="muted">${t.session_id}</span></div>`;
        const a=document.createElement('button'); a.textContent='Approve'; a.onclick=async()=>{await resolveSessionApproval(t.id, true);};
        const r=document.createElement('button'); r.textContent='Reject'; r.onclick=async()=>{await resolveSessionApproval(t.id, false);};
        row.append(a,r); el.appendChild(row);
      });
      if (!accessRequests.length && !tasks.length) {
        el.innerHTML = '<div class="muted small-text">No pending approvals.</div>';
      }
    });
  })();
  try {
    return await approvalsRequest;
  } finally {
    approvalsRequest = null;
  }
}

