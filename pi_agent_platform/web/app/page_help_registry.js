(function () {
  const HELP = {
    dashboard: {
      title: 'Operations dashboard',
      purpose: 'Use the dashboard for a concise operational summary and the PAC Component Atlas.',
      tips: ['Use Widgets to choose visible dashboard panels.', 'Use the atlas controls inside the panel for map-specific refresh and reset.', 'Use the notification bell for events instead of footer status text.'],
    },
    sessions: {
      title: 'Sessions',
      purpose: 'Sessions combine a task, profile, model, endpoint, workspace, permissions, and the resulting timeline.',
      tips: ['Create sessions with the + menu or the page action.', 'Keep endpoint and workspace choices explicit before sending work.', 'Review thought/tool events from the timeline when a task stalls.'],
    },
    endpoints: {
      title: 'Endpoints',
      purpose: 'Endpoints are machines that can run workloads, expose local tools, and host workspaces.',
      tips: ['Use Inventory for existing machines.', 'Use Add endpoint for the guided registration flow.', 'Default workspaces and available tool packages should be visible before scheduling work.'],
    },
    providers: {
      title: 'Providers',
      purpose: 'Providers describe external model services PAC agents can call.',
      tips: ['Register providers before adding models.', 'Keep credentials in the Credentials page.', 'Provider health should be checked before using a model in sessions.'],
    },
    models: {
      title: 'Models',
      purpose: 'Models are provider-backed capabilities used by sessions and profiles.',
      tips: ['Sync from provider to catch context-window changes.', 'Do not store profile instructions here.', 'Use profiles for task behavior and context policy.'],
    },
    profiles: {
      title: 'Profiles',
      purpose: 'Profiles define instructions and context policy; they should not own provider or tool inventory.',
      tips: ['Use profiles to constrain behavior and context size.', 'Group access can decide who may use a profile.', 'Tool availability comes from workspace and endpoint context.'],
    },
    workspaces: {
      title: 'Workspaces',
      purpose: 'Workspaces bound task context and files to a safe execution scope.',
      tips: ['Give endpoints a default workspace.', 'Use shared storage only where collaboration is intended.', 'Avoid mixing unrelated projects in one workspace.'],
    },
    credentials: {
      title: 'Credentials',
      purpose: 'Credentials store variables and write-only secrets separately from personal user settings.',
      tips: ['Use variables for non-secret configuration.', 'Use secrets for sensitive material.', 'Review audit information after changes.'],
    },
    'users-groups': {
      title: 'Users & groups',
      purpose: 'Manage people, groups, service accounts, and resource grants from the directory surface.',
      tips: ['Use the guided create menus rather than inline ad-hoc forms.', 'Assign group access to profiles and resources.', 'Check the access preview before saving grants.'],
    },
    updates: {
      title: 'Update Center',
      purpose: 'Version, changelog, release checks, feature packs, source module updates, backups, and local diffs live here.',
      tips: ['Preview updates before applying them.', 'Backups preserve local changes made during PAC app updates.', 'Use local diffs to inspect your own changes against a previous version.'],
    },
    observability: {
      title: 'Observe',
      purpose: 'Inspect events, status, and embedded observability signals without leaving PAC.',
      tips: ['Use filters before reading long event streams.', 'The notification bell is the global event entry point.', 'Use page-local export actions for diagnostics.'],
    },
  };

  function activeRoute() {
    return document.body?.dataset.shellRoute || window.__pacActiveShellRoute || 'dashboard';
  }

  function get(route = activeRoute()) {
    return HELP[route] || HELP[String(route || '').replace(/^settings-/, '')] || {
      title: document.getElementById('pacPageTitle')?.textContent || 'PAC page',
      purpose: document.getElementById('pacShellContext')?.textContent || 'This page follows the PAC shell contract.',
      tips: ['Use the Page Masthead for page actions.', 'Use the Page Toolbar for search, filters, and list-level actions.', 'Use the Primary Navigation Rail for main navigation.'],
    };
  }

  window.PacPageHelp = {get};
})();
