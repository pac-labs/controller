// Header, theme, user-menu, settings, and setup-wizard bindings

document.getElementById('refresh').onclick=()=>init();
const themeModeSelect = document.getElementById('themeMode');
if (themeModeSelect) themeModeSelect.onchange = () => applyThemeMode(themeModeSelect.value || 'system');
const authTokenInput = document.getElementById('token');
if (authTokenInput) authTokenInput.addEventListener('input', () => renderHeaderAuthBox());
document.getElementById('loginBtn')?.addEventListener('click', () => openLoginModal(authStatus?.needs_setup ? 'setup' : 'login'));
document.getElementById('userChipLogout')?.addEventListener('click', () => {
  document.getElementById('userMenu')?.setAttribute('hidden', '');
  document.getElementById('userChip')?.setAttribute('aria-expanded', 'false');
  document.querySelector('.user-menu-wrap')?.classList.remove('open');
  logoutUser();
});
document.querySelectorAll('.settings-sub-btn').forEach((btn) => {
  btn.addEventListener('click', () => switchSettingsPanel(btn.dataset.settingsPanel));
});
document.getElementById('userChip')?.addEventListener('click', (ev) => {
  ev.stopPropagation();
  const menu = document.getElementById('userMenu');
  const chip = document.getElementById('userChip');
  const wrap = chip?.closest('.user-menu-wrap');
  if (!menu || !chip || chip.hidden) return;
  const open = !menu.hasAttribute('hidden');
  if (open) {
    menu.setAttribute('hidden', '');
    chip.setAttribute('aria-expanded', 'false');
    wrap?.classList.remove('open');
  } else {
    menu.removeAttribute('hidden');
    chip.setAttribute('aria-expanded', 'true');
    wrap?.classList.add('open');
  }
});
document.getElementById('userMenuSettings')?.addEventListener('click', () => {
  document.getElementById('userMenu')?.setAttribute('hidden', '');
  document.getElementById('userChip')?.setAttribute('aria-expanded', 'false');
  document.querySelector('.user-menu-wrap')?.classList.remove('open');
  openPersonalSettingsModal().catch((e)=>paneError('Personal settings could not be opened', e.message || String(e)));
});
document.addEventListener('click', (ev) => {
  const menu = document.getElementById('userMenu');
  const chip = document.getElementById('userChip');
  if (!menu || !chip) return;
  if (!menu.hasAttribute('hidden') && !menu.contains(ev.target) && !chip.contains(ev.target)) {
    menu.setAttribute('hidden', '');
    chip.setAttribute('aria-expanded', 'false');
    chip.closest('.user-menu-wrap')?.classList.remove('open');
  }
});
if (document.getElementById('dismissSetupWizard')) document.getElementById('dismissSetupWizard').onclick = () => hideSetupWizard();
if (document.getElementById('setupWizardBack')) document.getElementById('setupWizardBack').onclick = () => { setupWizardStepIndex = Math.max(0, setupWizardStepIndex - 1); renderSetupWizard(); };
if (document.getElementById('setupWizardNext')) document.getElementById('setupWizardNext').onclick = () => advanceSetupWizard(1).catch(e => paneError('Setup step failed', e.message || String(e)));
if (document.getElementById('setupWizardDone')) document.getElementById('setupWizardDone').onclick = () => completeSetupWizard().catch(e => paneError('Setup completion failed', e.message || String(e)));
if (document.getElementById('recheckSetupWizard')) document.getElementById('recheckSetupWizard').onclick = () => completeSetupWizard().catch(e => paneError('Setup recheck failed', e.message || String(e)));
