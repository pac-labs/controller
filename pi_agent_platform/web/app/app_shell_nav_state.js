(function () {
  const RAIL_KEY = 'pac-shell-nav-collapsed';
  const SECTION_KEY = 'pac-shell-nav-section-collapsed';

  function readJson(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return fallback;
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : fallback;
    } catch (_) {
      return fallback;
    }
  }

  function writeJson(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value || {})); } catch (_) {}
  }

  function isRailCollapsed() {
    try { return localStorage.getItem(RAIL_KEY) === '1'; } catch (_) { return false; }
  }

  function setRailCollapsed(collapsed) {
    try { localStorage.setItem(RAIL_KEY, collapsed ? '1' : '0'); } catch (_) {}
  }

  function sectionState() {
    return readJson(SECTION_KEY, {});
  }

  function isSectionCollapsed(groupId) {
    if (!groupId) return false;
    return sectionState()[groupId] === true;
  }

  function setSectionCollapsed(groupId, collapsed) {
    if (!groupId) return;
    const state = sectionState();
    if (collapsed) state[groupId] = true;
    else delete state[groupId];
    writeJson(SECTION_KEY, state);
  }

  function toggleSection(groupId) {
    const next = !isSectionCollapsed(groupId);
    setSectionCollapsed(groupId, next);
    return next;
  }

  window.PacShellNavState = {
    isRailCollapsed,
    setRailCollapsed,
    isSectionCollapsed,
    setSectionCollapsed,
    toggleSection,
    sectionState,
  };
})();
