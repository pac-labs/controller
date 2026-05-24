// Directory & Access shared state, constants, and labels.

// Directory & Access UI pass 6. Overrides the legacy user/group admin renderer with a directory-first surface.

const directoryAccessState = {
  tree: null,
  users: [],
  groups: [],
  service_accounts: [],
  endpoints: [],
  providers: [],
  certificate_identities: [],
  credentials: [],
  selectedKind: 'folder',
  selectedId: 'people',
  search: '',
};

const DIRECTORY_GRANT_PRESETS = [
  ['profile:*:use', 'Can use all profiles'],
  ['workspace:*:read', 'Can view all workspaces'],
  ['workspace:*:write', 'Can edit all workspaces'],
  ['agent_context:*:use', 'Can use all agent contexts'],
  ['agent_context:*:write', 'Can edit all agent contexts'],
  ['endpoint:*:execute', 'Can execute endpoint jobs'],
  ['provider:*:use', 'Can use model providers'],
  ['diagnostics:*:read', 'Can view diagnostics'],
  ['system:*:manage', 'Full PAC administration'],
];


const DIRECTORY_GRANT_RESOURCE_TYPES = [
  ['profile', 'Profile'],
  ['workspace', 'Workspace'],
  ['agent_context', 'Agent context'],
  ['source_context', 'Source context'],
  ['secret', 'Secret'],
  ['session', 'Session'],
  ['diagnostics', 'Diagnostics'],
  ['model_usage', 'Model usage'],
  ['endpoint', 'Endpoint'],
  ['provider', 'Provider'],
  ['system', 'System'],
];

const DIRECTORY_GRANT_ACTIONS = ['use', 'read', 'write', 'execute', 'create', 'manage'];

const DIRECTORY_FOLDERS = [
  ['people', 'People', 'user', 'users'],
  ['groups', 'Groups', 'group', 'groups'],
  ['service_accounts', 'Service Accounts', 'service_account', 'service_accounts'],
  ['endpoints', 'Endpoints', 'endpoint', 'endpoints'],
  ['providers', 'Providers', 'provider', 'providers'],
  ['certificate_identities', 'Certificate Identities', 'certificate_identity', 'certificate_identities'],
  ['credentials', 'Credentials', 'credential', 'credentials'],
];

const DIRECTORY_KIND_LABELS = {
  user: 'User',
  group: 'Group',
  service_account: 'Service account',
  endpoint: 'Endpoint identity',
  provider: 'Provider identity',
  certificate_identity: 'Certificate identity',
  credential: 'Credential',
};
