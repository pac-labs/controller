(function () {
  function normalize(value) {
    return String(value || '').trim().toLowerCase();
  }

  function searchableText(button) {
    return [button.textContent, button.title, button.dataset.shellAliases].map(normalize).join(' ');
  }

  function itemMatches(button, query) {
    if (!query) return true;
    return searchableText(button).includes(query);
  }

  function sectionMatches(section, query) {
    if (!query) return true;
    const title = normalize(section.querySelector('.shell-nav-section-title')?.textContent);
    const description = normalize(section.querySelector('.shell-nav-section-description')?.textContent);
    if (title.includes(query) || description.includes(query)) return true;
    return Array.from(section.querySelectorAll('.shell-nav-item')).some((button) => itemMatches(button, query));
  }

  function visibleItems(container) {
    return Array.from(container?.querySelectorAll('.shell-nav-item') || []).filter((button) => !button.hidden && !button.closest('.shell-nav-section')?.hidden);
  }

  function clearHighlighted(container) {
    container?.querySelectorAll('.shell-nav-item.keyboard-target').forEach((button) => button.classList.remove('keyboard-target'));
  }

  function highlightItem(container, index) {
    const items = visibleItems(container);
    clearHighlighted(container);
    if (!items.length) return -1;
    const nextIndex = (index + items.length) % items.length;
    items[nextIndex].classList.add('keyboard-target');
    items[nextIndex].scrollIntoView({block: 'nearest'});
    return nextIndex;
  }

  function filterNav(container, query) {
    const hasQuery = Boolean(query);
    container?.classList.toggle('shell-nav-filtering', hasQuery);
    container?.querySelectorAll('.shell-nav-section').forEach((section) => {
      const visibleSection = sectionMatches(section, query);
      section.hidden = !visibleSection;
      if (!visibleSection) return;
      section.querySelectorAll('.shell-nav-item').forEach((button) => {
        button.hidden = !itemMatches(button, query);
      });
      if (hasQuery) section.classList.remove('collapsed');
      if (!hasQuery) {
        const groupId = section.dataset.shellGroup || '';
        section.classList.toggle('collapsed', window.PacShellNavState?.isSectionCollapsed(groupId) || false);
      }
    });
    const resultCount = visibleItems(container).length;
    const search = document.getElementById('pacShellNavSearch');
    if (search) search.dataset.resultCount = String(resultCount);
    return resultCount;
  }

  function setAllSections(collapsed, helpers) {
    const groups = typeof helpers?.navGroups === 'function' ? helpers.navGroups() : [];
    groups.forEach((group) => {
      window.PacShellNavState?.setSectionCollapsed(group.id, collapsed);
      helpers?.applySectionState?.(group.id, collapsed);
    });
  }

  function bindKeyboard(container) {
    const search = document.getElementById('pacShellNavSearch');
    if (!search) return;
    let keyboardIndex = -1;
    search.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowDown') {
        ev.preventDefault();
        keyboardIndex = highlightItem(container, keyboardIndex + 1);
      } else if (ev.key === 'ArrowUp') {
        ev.preventDefault();
        keyboardIndex = highlightItem(container, keyboardIndex - 1);
      } else if (ev.key === 'Enter') {
        const target = container?.querySelector('.shell-nav-item.keyboard-target') || visibleItems(container)[0];
        if (target) {
          ev.preventDefault();
          target.click();
          search.blur();
        }
      } else if (ev.key === 'Escape') {
        search.value = '';
        filterNav(container, '');
        clearHighlighted(container);
        keyboardIndex = -1;
      }
    });
    search.addEventListener('input', () => {
      keyboardIndex = -1;
      clearHighlighted(container);
      filterNav(container, normalize(search.value));
    });
  }

  function bind(container, helpers = {}) {
    bindKeyboard(container);
    document.getElementById('pacShellNavExpandAll')?.addEventListener('click', () => setAllSections(false, helpers));
    document.getElementById('pacShellNavCollapseAll')?.addEventListener('click', () => setAllSections(true, helpers));
  }

  window.PacShellNavTools = {bind, filterNav, visibleItems};
})();
