// Directory & Access API service. Keeps endpoints in one place so UI modules stay focused.

const DirectoryApi = {
  async loadAll() {
    const [tree, users, groups, serviceAccounts, endpoints, providers, certificates, credentials] = await Promise.all([
      api('/v1/directory/tree'),
      api('/v1/directory/principals?kind=user'),
      api('/v1/directory/groups'),
      api('/v1/directory/principals?kind=service_account').catch(() => []),
      api('/v1/directory/principals?kind=endpoint').catch(() => []),
      api('/v1/directory/principals?kind=provider').catch(() => []),
      api('/v1/directory/principals?kind=certificate_identity').catch(() => []),
      api('/v1/auth/tokens').catch(() => []),
    ]);
    return {tree, users, groups, serviceAccounts, endpoints, providers, certificates, credentials};
  },
  createUser(payload) {
    return api('/v1/directory/users', {method: 'POST', body: JSON.stringify(payload)});
  },
  createGroup(payload) {
    return api('/v1/directory/groups', {method: 'POST', body: JSON.stringify(payload)});
  },
  createServiceAccount(payload) {
    return api('/v1/directory/service-accounts', {method: 'POST', body: JSON.stringify(payload)});
  },
  effectiveAccess(principalId) {
    return api(`/v1/directory/principals/${encodeURIComponent(principalId)}/effective-access`);
  },
  principalCredentials(principalId) {
    return api(`/v1/directory/principals/${encodeURIComponent(principalId)}/credentials`);
  },
  createToken(principalId, payload) {
    return api(`/v1/directory/principals/${encodeURIComponent(principalId)}/tokens`, {method: 'POST', body: JSON.stringify(payload)});
  },
  createCertificate(principalId, payload) {
    return api(`/v1/directory/principals/${encodeURIComponent(principalId)}/certificates`, {method: 'POST', body: JSON.stringify(payload)});
  },
  revokeCredential(credentialId) {
    return api(`/v1/directory/credentials/${encodeURIComponent(credentialId)}`, {method: 'DELETE'});
  },
  addGroupMember(groupId, member) {
    return api(`/v1/directory/groups/${encodeURIComponent(groupId)}/members`, {method: 'POST', body: JSON.stringify(member)});
  },
  removeGroupMember(groupId, kind, id) {
    return api(`/v1/directory/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, {method: 'DELETE'});
  },
  updateGroup(groupId, payload) {
    return api(`/v1/directory/groups/${encodeURIComponent(groupId)}`, {method: 'PUT', body: JSON.stringify(payload)});
  },
  deleteGroup(groupId) {
    return api(`/v1/directory/groups/${encodeURIComponent(groupId)}`, {method: 'DELETE'});
  },
};
