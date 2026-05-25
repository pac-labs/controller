(function () {
  const groups = [
    {
      id: 'operate',
      label: 'Operate',
      description: 'Daily PAC control and execution flow.',
      items: [
        {id: 'dashboard', tab: 'dashboard', label: 'Dashboard', icon: '⌂', aliases: ['home', 'overview', 'status'], description: 'Overview and system status.', mastheadMode: 'normal'},
        {id: 'atlas', tab: 'dashboard', label: 'Atlas', icon: '⌘', focus: 'dashboardTopologyMap', aliases: ['map', 'topology', 'graph', 'components'], description: 'Component map and dependencies.', mastheadMode: 'compact'},
        {id: 'sessions', tab: 'sessions-tab', label: 'Sessions', icon: '◫', aliases: ['chat', 'tasks', 'runs', 'composer'], description: 'Agent conversations and task runs.', mastheadMode: 'compact'},
      ],
    },
    {
      id: 'build',
      label: 'Build',
      description: 'Source work, workspaces, and available tools.',
      items: [
        {id: 'ide', tab: 'sources-tab', label: 'IDE', icon: '▣', aliases: ['sources', 'code', 'files', 'workbench'], description: 'Source browser and editing.'},
        {id: 'workspaces', tab: 'workspaces-tab', label: 'Workspaces', icon: '▤', aliases: ['workspace', 'storage', 'context boundary'], description: 'Bounded execution context.'},
        {id: 'tools', tab: 'tools-tab', label: 'Tools', icon: '⚒', aliases: ['packages', 'binaries', 'plugins'], description: 'Endpoint-local binaries and packages.'},
      ],
    },
    {
      id: 'agents',
      label: 'Agents',
      description: 'Agent runtime context and model behavior.',
      items: [
        {id: 'contexts', tab: 'contexts-tab', label: 'Contexts', icon: '◌', aliases: ['agent context', 'defaults'], description: 'Agent contexts and defaults.'},
        {id: 'models', tab: 'models-tab', label: 'Models', icon: '◇', aliases: ['llm', 'model registry'], description: 'Registered external models.'},
        {id: 'profiles', tab: 'profiles-tab', label: 'Profiles', icon: '▧', aliases: ['instructions', 'roles', 'profile access'], description: 'Instructions, context size, and access policy.'},
      ],
    },
    {
      id: 'admin',
      label: 'Configuration',
      description: 'System setup separated from personal user controls.',
      items: [
        {id: 'providers', tab: 'providers-tab', label: 'Providers', icon: '◎', aliases: ['openai', 'lm studio', 'ollama', 'provider'], description: 'Model and service providers.'},
        {id: 'endpoints', tab: 'runners-tab', label: 'Endpoints', icon: '⌁', aliases: ['runners', 'agents', 'machines', 'windows'], description: 'Machines that run workloads.'},
        {id: 'credentials', tab: 'settings-tab', settingsPanel: 'credentials', label: 'Credentials', icon: '◈', aliases: ['secrets', 'variables', 'tokens', 'keys'], description: 'Workspace variables and endpoint secret material.'},
        {id: 'users-groups', tab: 'settings-tab', settingsPanel: 'users', label: 'Users & groups', icon: '◍', aliases: ['users', 'groups', 'directory', 'service accounts', 'identity'], description: 'Access, groups, service accounts, and directory controls.'},
        {id: 'approvals-policy', tab: 'settings-tab', settingsPanel: 'approvals', label: 'Approvals', icon: '✓', aliases: ['approval', 'policy', 'requests'], description: 'Governed task approvals and access requests.'},
        {id: 'updates', tab: 'settings-tab', settingsPanel: 'updates', label: 'Update Center', icon: '↻', aliases: ['updates', 'release', 'version', 'changelog'], description: 'Controller versions, release checks, changelog, backups, and feature packs.', mastheadMode: 'sticky'},
        {id: 'runtime', tab: 'settings-tab', settingsPanel: 'pi-dev', label: 'Runtime', icon: 'π', aliases: ['pi.dev', 'pac agent', 'controller agent'], description: 'pi.dev runtime and controller agent settings.'},
        {id: 'service-mode', tab: 'settings-tab', settingsPanel: 'service', label: 'Service', icon: '◧', description: 'Service mode and controller runtime service status.'},
        {id: 'network-security', tab: 'settings-tab', settingsPanel: 'tls', label: 'TLS / CA', icon: '♢', aliases: ['tls', 'ca', 'certificates', 'trust', 'https'], description: 'TLS, certificate authority, and trust material.'},
        {id: 'proxy-routes', tab: 'settings-tab', settingsPanel: 'proxy-routes', label: 'Proxy routes', icon: '⇄', aliases: ['proxy', 'routes', 'routing'], description: 'Internal proxy route visibility.'},
        {id: 'raw-config', tab: 'settings-tab', settingsPanel: 'config', label: 'Raw config', icon: '{}', aliases: ['json', 'config', 'advanced'], description: 'Inspect and edit controller configuration.'},
      ],
    },
    {
      id: 'observe',
      label: 'Observe',
      description: 'Runtime visibility and event activity.',
      items: [
        {id: 'observability', tab: 'observe-tab', label: 'Observability', icon: '◉', aliases: ['observe', 'metrics', 'logs', 'traces'], description: 'Metrics, logs, traces, and stores.'},
        {id: 'events', tab: 'events-panel-proxy', label: 'Events', icon: '✦', aliases: ['notifications', 'activity', 'event rail'], description: 'Open the live events rail.'},
      ],
    },
  ];

  window.PAC_NAV_GROUPS = groups;
})();
