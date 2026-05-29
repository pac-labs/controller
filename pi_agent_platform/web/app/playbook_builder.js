(function () {
  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function slug(value) {
    return String(value || 'custom-playbook')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'custom-playbook';
  }

  function yamlScalar(value) {
    const text = String(value ?? '');
    if (!text) return '""';
    if (/^[a-zA-Z0-9_.:\/@-]+$/.test(text)) return text;
    return JSON.stringify(text);
  }

  function linesForParameters(raw) {
    let rows = [];
    try { rows = JSON.parse(raw || '[]'); } catch { rows = []; }
    if (!Array.isArray(rows) || !rows.length) return ['parameters: []'];
    const out = ['parameters:'];
    rows.forEach((row) => {
      if (!row || !row.name) return;
      out.push(`  - name: ${slug(row.name)}`);
      out.push(`    type: ${row.type || 'string'}`);
      if (row.required) out.push('    required: true');
      if (row.description) out.push(`    description: ${yamlScalar(row.description)}`);
      if (row.default !== undefined && row.default !== null && row.default !== '') out.push(`    default: ${yamlScalar(row.default)}`);
    });
    return out;
  }

  function linesForSteps(raw) {
    let rows = [];
    try { rows = JSON.parse(raw || '[]'); } catch { rows = []; }
    if (!Array.isArray(rows) || !rows.length) rows = [{id:'start', title:'Start', action:'note', prompt:'Playbook created from the visual builder.'}];
    const out = ['steps:'];
    rows.forEach((row, index) => {
      const id = slug(row.id || `step-${index + 1}`);
      out.push(`  - id: ${id}`);
      if (row.title) out.push(`    title: ${yamlScalar(row.title)}`);
      out.push(`    action: ${row.action || 'note'}`);
      if (row.tool) out.push(`    tool: ${yamlScalar(row.tool)}`);
      if (row.prompt) out.push(`    prompt: ${yamlScalar(row.prompt)}`);
      if (row.depends_on) {
        const deps = String(row.depends_on).split(',').map((v) => slug(v)).filter(Boolean);
        if (deps.length) out.push(`    depends_on: [${deps.join(', ')}]`);
      }
      if (row.gate) {
        out.push('    gate:');
        out.push(`      type: ${row.gate}`);
        out.push(`      message: ${yamlScalar(row.gate_message || `Review ${id} before continuing`)}`);
      }
      if (row.input && typeof row.input === 'object') {
        out.push('    input:');
        Object.entries(row.input).forEach(([key, value]) => out.push(`      ${key}: ${yamlScalar(value)}`));
      }
    });
    return out;
  }

  function buildYaml() {
    const id = slug(document.getElementById('playbookBuilderId')?.value || 'custom-playbook');
    const title = document.getElementById('playbookBuilderTitle')?.value || id;
    const description = document.getElementById('playbookBuilderDescription')?.value || '';
    const params = document.getElementById('playbookBuilderParameters')?.value || '[]';
    const steps = document.getElementById('playbookBuilderSteps')?.value || '[]';
    return [
      `id: ${id}`,
      `title: ${yamlScalar(title)}`,
      description ? `description: ${yamlScalar(description)}` : 'description: ""',
      'version: "1"',
      ...linesForParameters(params),
      ...linesForSteps(steps),
    ].join('\n') + '\n';
  }

  function syncPreview() {
    const preview = document.getElementById('playbookBuilderYamlPreview');
    if (preview) preview.value = buildYaml();
  }

  async function createPlaybook() {
    const status = document.getElementById('playbookBuilderStatus');
    try {
      const yaml = buildYaml();
      const overwrite = !!document.getElementById('playbookBuilderOverwrite')?.checked;
      const result = await api('/v1/playbooks/import', {method: 'POST', body: JSON.stringify({yaml, overwrite})});
      if (status) status.textContent = `Created ${result.playbook?.id || 'playbook'}`;
      if (typeof loadPlaybooksPanel === 'function') await loadPlaybooksPanel();
    } catch (err) {
      if (status) status.textContent = err.message || String(err);
    }
  }

  function openPlaybookBuilder() {
    let modal = document.getElementById('playbookBuilderModal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'playbookBuilderModal';
      modal.className = 'modal-backdrop hidden';
      modal.innerHTML = `<div class="modal card playbook-builder-modal">
        <div class="section-heading compact-heading"><div><h2>Create playbook</h2><p class="muted small-text">Build a typed playbook without starting from raw YAML. Advanced fields can still be edited in the preview.</p></div><button class="ghost-button" data-close>Close</button></div>
        <div class="playbook-builder-grid">
          <label class="form-row"><span>ID</span><input id="playbookBuilderId" value="custom-playbook"></label>
          <label class="form-row"><span>Title</span><input id="playbookBuilderTitle" value="Custom playbook"></label>
          <label class="form-row wide"><span>Description</span><input id="playbookBuilderDescription" value="Repeatable PAC workflow."></label>
          <label class="form-row wide"><span>Parameters JSON</span><textarea id="playbookBuilderParameters" spellcheck="false">[{"name":"repository_url","type":"string","required":true},{"name":"container_image","type":"string","default":"rust:latest"}]</textarea></label>
          <label class="form-row wide"><span>Steps JSON</span><textarea id="playbookBuilderSteps" spellcheck="false">[{"id":"review","title":"Review request","action":"note","prompt":"Review the supplied inputs."},{"id":"approve","title":"Approve execution","action":"checkpoint","gate":"approve","gate_message":"Approve before continuing","depends_on":"review"}]</textarea></label>
          <label class="form-row wide"><span>Generated YAML preview</span><textarea id="playbookBuilderYamlPreview" spellcheck="false"></textarea></label>
        </div>
        <label class="checkbox-row"><input id="playbookBuilderOverwrite" type="checkbox"> <span>Overwrite existing playbook with same id</span></label>
        <div class="button-row compact-row"><button id="playbookBuilderCreate" class="primary-button" type="button">Create playbook</button><button id="playbookBuilderRefresh" class="ghost-button" type="button">Refresh preview</button><span id="playbookBuilderStatus" class="muted small-text"></span></div>
      </div>`;
      document.body.appendChild(modal);
      modal.querySelector('[data-close]').onclick = () => modal.classList.add('hidden');
      modal.querySelector('#playbookBuilderCreate').onclick = createPlaybook;
      modal.querySelector('#playbookBuilderRefresh').onclick = syncPreview;
      modal.querySelectorAll('input,textarea').forEach((el) => el.addEventListener('input', syncPreview));
    }
    modal.classList.remove('hidden');
    syncPreview();
  }

  document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('playbooksCreate');
    if (button) button.onclick = openPlaybookBuilder;
  });

  window.openPlaybookBuilder = openPlaybookBuilder;
})();
