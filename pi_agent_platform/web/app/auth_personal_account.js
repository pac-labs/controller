// Personal account API helpers used by the personal settings modal.

function closePersonalSettingsModal() {
  document.getElementById('personalSettingsModal')?.remove();
}

async function loadPersonalSettingsData() {
  const [me, tokens, ram] = await Promise.all([
    api('/v1/users/me'),
    api('/v1/users/me/tokens').catch(() => []),
    api('/v1/users/me/ram').catch(() => ({content: ''})),
  ]);
  return {me, tokens, ram};
}

function renderPersonalTokens(target, tokens, latestToken = '') {
  if (!target) return;
  const items = Array.isArray(tokens) ? tokens : [];
  target.innerHTML = `
    ${latestToken ? `<div class="inline-result">${escapeHtml(latestToken)}</div>` : ''}
    ${items.length ? items.map((item) => `<div class="row"><div><b>${escapeHtml(item.username || currentUser?.username || 'token')}</b><br><span class="muted small-text">expires ${escapeHtml(item.expires_at || '-')}</span></div><div class="button-row"><button class="ghost-button revoke-self-token-btn" data-token="${escapeHtml(item.id || item.token || '')}" type="button">Revoke</button></div></div>`).join('') : '<div class="muted small-text">No personal tokens yet.</div>'}`;
  target.querySelectorAll('.revoke-self-token-btn').forEach((btn) => btn.addEventListener('click', async () => {
    const token = btn.dataset.token || '';
    if (!token || !confirm('Revoke this token?')) return;
    await api(`/v1/users/me/tokens/${encodeURIComponent(token)}`, {method: 'DELETE'});
    const refreshed = await api('/v1/users/me/tokens').catch(() => []);
    renderPersonalTokens(target, refreshed);
  }));
}
