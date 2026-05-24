(function () {
  function resultBox() {
    let box = document.getElementById('rawConfigValidationResult');
    if (!box) {
      const editor = document.getElementById('configEditor');
      box = document.createElement('pre');
      box.id = 'rawConfigValidationResult';
      box.className = 'inline-result compact-result raw-config-result';
      editor?.insertAdjacentElement('afterend', box);
    }
    return box;
  }

  function parseConfig() {
    const editor = document.getElementById('configEditor');
    const text = editor?.value || '{}';
    return JSON.parse(text);
  }

  function setResult(message, kind = '') {
    const box = resultBox();
    if (!box) return;
    box.hidden = false;
    box.className = `inline-result compact-result raw-config-result ${kind}`.trim();
    box.textContent = message;
  }

  function validateConfig() {
    try {
      const parsed = parseConfig();
      const keys = Object.keys(parsed || {}).sort();
      setResult(`Valid JSON. Top-level keys: ${keys.join(', ') || '(none)'}`, 'ok-text');
      return parsed;
    } catch (error) {
      setResult(`Invalid JSON: ${error.message}`, 'warn-text');
      return null;
    }
  }

  async function saveRawConfig() {
    const parsed = validateConfig();
    if (!parsed) return;
    const button = document.getElementById('saveConfig');
    if (button) button.disabled = true;
    try {
      await window.api('/v1/config', {method: 'PUT', body: JSON.stringify({config: parsed})});
      setResult('Configuration saved. Reloading PAC state…', 'ok-text');
      await window.init?.();
    } catch (error) {
      setResult(`Save failed: ${error.message}`, 'warn-text');
    } finally {
      if (button) button.disabled = false;
    }
  }

  function bindRawConfigEditor() {
    document.getElementById('saveConfig')?.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      saveRawConfig();
    }, true);
    document.getElementById('configEditor')?.addEventListener('input', () => {
      const box = document.getElementById('rawConfigValidationResult');
      if (box) box.hidden = true;
    });
    document.addEventListener('pac:validate-config', validateConfig);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bindRawConfigEditor);
  else bindRawConfigEditor();

  window.validateRawConfigEditor = validateConfig;
})();
