// Release apply confirmation overlay helpers.

function openUpdateConfirmOverlay(meta) {
  const overlay = document.getElementById('updateConfirmOverlay');
  if (!overlay) return;
  const title = document.getElementById('updateConfirmTitle');
  const message = document.getElementById('updateConfirmMessage');
  const body = document.getElementById('updateConfirmBody');
  const proceed = document.getElementById('updateConfirmProceed');
  const cancel = document.getElementById('updateConfirmCancel');
  const currentVersion = String(meta?.current_version || config?.version || config?.setup_status?.version || '-');
  const nextVersion = String(meta?.latest_version || '').trim();
  if (title) title.textContent = 'Apply PAC release';
  if (message) message.textContent = `Install ${nextVersion ? `v${nextVersion}` : 'the latest release'} and restart PAC?`;
  if (body) {
    const bullets = Array.isArray(meta?.compare_changes) ? meta.compare_changes.slice(0, 8) : [];
    body.innerHTML = `
      <div class="updates-detail-copy">
        <div>Current version: <b>v${escapeHtml(currentVersion)}</b></div>
        <div>Target version: <b>${escapeHtml(nextVersion ? `v${nextVersion}` : 'latest')}</b></div>
        ${bullets.length ? `<div style="margin-top:.65rem"><b>Included changes</b></div><ul>${bullets.map((change) => `<li>${escapeHtml(String(change))}</li>`).join('')}</ul>` : ''}
      </div>`;
  }
  if (proceed) {
    proceed.disabled = false;
    proceed.textContent = 'Apply and restart';
  }
  if (cancel) cancel.hidden = false;
  overlay.hidden = false;
  delete overlay.dataset.locked;
}

function closeUpdateConfirmOverlay(force = false) {
  const overlay = document.getElementById('updateConfirmOverlay');
  if (!overlay) return;
  if (force || !overlay.dataset.locked) {
    overlay.hidden = true;
    delete overlay.dataset.locked;
  }
}

function setUpdateConfirmOverlayRestarting(version, seconds = 18) {
  const overlay = document.getElementById('updateConfirmOverlay');
  if (!overlay) return;
  const title = document.getElementById('updateConfirmTitle');
  const message = document.getElementById('updateConfirmMessage');
  const body = document.getElementById('updateConfirmBody');
  const proceed = document.getElementById('updateConfirmProceed');
  const cancel = document.getElementById('updateConfirmCancel');
  overlay.hidden = false;
  overlay.dataset.locked = 'true';
  if (title) title.textContent = 'Restarting PAC';
  if (message) message.textContent = `${version ? `v${version}` : 'The release'} is being applied.`;
  if (body) {
    body.innerHTML = `<div class="updates-detail-copy"><div>PAC is restarting.</div><div>Refresh when the UI returns.</div></div>`;
  }
  if (proceed) {
    proceed.disabled = true;
    proceed.textContent = 'Restarting…';
  }
  if (cancel) cancel.hidden = true;
}
