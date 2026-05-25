// Release apply confirmation overlay helpers.

function updateConfirmOverlayElements() {
  return {
    overlay: document.getElementById('updateConfirmOverlay'),
    title: document.getElementById('updateConfirmTitle'),
    message: document.getElementById('updateConfirmMessage'),
    body: document.getElementById('updateConfirmBody'),
    proceed: document.getElementById('updateConfirmProceed'),
    cancel: document.getElementById('updateConfirmCancel'),
  };
}

function openUpdateConfirmOverlay(meta) {
  const {overlay, title, message, body, proceed, cancel} = updateConfirmOverlayElements();
  if (!overlay) return;
  const currentVersion = String(meta?.current_version || config?.version || config?.setup_status?.version || '-');
  const nextVersion = String(meta?.latest_version || '').trim();
  const changeList = Array.isArray(meta?.compare_changes) ? meta.compare_changes : (Array.isArray(meta?.changes) ? meta.changes : []);
  if (title) title.textContent = 'Apply PAC release';
  if (message) message.textContent = `Install ${nextVersion ? `v${nextVersion}` : 'the latest release'} and restart PAC?`;
  if (body) {
    const bullets = changeList.slice(0, 8);
    body.innerHTML = `
      <div class="updates-detail-copy">
        <div>Current version: <b>v${escapeHtml(currentVersion)}</b></div>
        <div>Target version: <b>${escapeHtml(nextVersion ? `v${nextVersion}` : 'latest')}</b></div>
        <p class="muted">PAC will install the selected release, preserve local changes, restart the controller, and reload this UI when the controller returns.</p>
        ${bullets.length ? `<div style="margin-top:.65rem"><b>Included changes</b></div><ul>${bullets.map((change) => `<li>${escapeHtml(String(change))}</li>`).join('')}</ul>` : ''}
      </div>`;
  }
  if (proceed) {
    proceed.disabled = false;
    proceed.textContent = 'Apply and restart';
  }
  if (cancel) cancel.hidden = false;
  overlay.hidden = false;
  overlay.removeAttribute('hidden');
  overlay.setAttribute('aria-busy', 'false');
  delete overlay.dataset.locked;
}

function closeUpdateConfirmOverlay(force = false) {
  const {overlay} = updateConfirmOverlayElements();
  if (!overlay) return;
  if (force || !overlay.dataset.locked) {
    overlay.hidden = true;
    overlay.setAttribute('hidden', '');
    overlay.removeAttribute('aria-busy');
    delete overlay.dataset.locked;
  }
}

function setUpdateConfirmOverlayRestarting(version, seconds = 18) {
  const {overlay, title, message, body, proceed, cancel} = updateConfirmOverlayElements();
  if (!overlay) return;
  overlay.hidden = false;
  overlay.removeAttribute('hidden');
  overlay.dataset.locked = 'true';
  overlay.setAttribute('aria-busy', 'true');
  const target = version ? `v${version}` : 'The selected release';
  if (title) title.textContent = 'Applying update and restarting PAC';
  if (message) message.textContent = `${target} is being installed.`;
  if (body) {
    body.innerHTML = `<div class="updates-detail-copy update-restart-progress">
      <div>PAC is restarting. Keep this tab open; the UI will reload automatically.</div>
      <div class="progress-track" aria-hidden="true"><i></i></div>
      <div id="updateRestartCountdown" class="muted small-text">Reloading in ${Number(seconds) || 18} seconds…</div>
    </div>`;
  }
  if (proceed) {
    proceed.disabled = true;
    proceed.textContent = 'Restarting…';
  }
  if (cancel) cancel.hidden = true;
}

function updateRestartCountdown(secondsLeft) {
  const countdown = document.getElementById('updateRestartCountdown');
  if (countdown) countdown.textContent = `Reloading in ${Math.max(0, secondsLeft)} seconds…`;
}
