// Collision-aware PAC Component Atlas layout helpers.

const ATLAS_NODE_GAP_X = 28;
const ATLAS_NODE_GAP_Y = 20;
const ATLAS_GROUP_MARGIN_X = 22;
const ATLAS_GROUP_HEADER_Y = 58;
const ATLAS_MIN_CANVAS_PAD = 80;
const ATLAS_BASE_WIDTH = 2240;
const ATLAS_BASE_HEIGHT = 1560;

function atlasNodeSize(node) {
  if (node?.kind === 'provider') return {w: 190, h: 68};
  if (node?.kind === 'model') return {w: 168, h: 58};
  if (node?.kind === 'capability') return {w: 132, h: 46};
  if ((node?.depth || '') === 'core') return {w: 238, h: 82};
  if ((node?.depth || '') === 'subcomponent') return {w: 204, h: 62};
  return {w: 204, h: 72};
}

function atlasRankNode(a, b) {
  const rank = {core: 0, instance: 1, subcomponent: 2};
  return (rank[a.depth] ?? 3) - (rank[b.depth] ?? 3)
    || String(a.parent || '').localeCompare(String(b.parent || ''))
    || String(a.label || a.id).localeCompare(String(b.label || b.id));
}

function atlasGroupRows(items, group) {
  const sorted = [...items].sort(atlasRankNode);
  const maxWidth = Math.max(180, group.w - (ATLAS_GROUP_MARGIN_X * 2));
  const rows = [];
  let row = [];
  let rowWidth = 0;
  sorted.forEach((node) => {
    const size = atlasNodeSize(node);
    const nextWidth = row.length ? rowWidth + ATLAS_NODE_GAP_X + size.w : size.w;
    if (row.length && nextWidth > maxWidth) {
      rows.push(row);
      row = [];
      rowWidth = 0;
    }
    row.push({node, size});
    rowWidth = row.length === 1 ? size.w : rowWidth + ATLAS_NODE_GAP_X + size.w;
  });
  if (row.length) rows.push(row);
  return rows;
}


function atlasProviderClusterRows(items) {
  const providers = items.filter((node) => node.kind === 'provider').sort(atlasRankNode);
  const unassigned = items.filter((node) => node.kind !== 'provider' && !node.parent).sort(atlasRankNode);
  const clusters = providers.map((provider) => ({
    provider,
    models: items.filter((node) => node.parent === provider.id && node.kind === 'model').sort(atlasRankNode),
    orphaned: [],
  }));
  const modelIds = new Set(clusters.flatMap((cluster) => cluster.models.map((node) => node.id)));
  clusters.forEach((cluster) => {
    cluster.capabilities = items.filter((node) => cluster.models.some((model) => node.parent === model.id)).sort(atlasRankNode);
  });
  const assignedIds = new Set([
    ...providers.map((node) => node.id),
    ...modelIds,
    ...clusters.flatMap((cluster) => cluster.capabilities.map((node) => node.id)),
  ]);
  const leftovers = items.filter((node) => !assignedIds.has(node.id) && !unassigned.includes(node)).sort(atlasRankNode);
  if (!clusters.length && (unassigned.length || leftovers.length)) {
    clusters.push({provider: null, models: [...unassigned, ...leftovers], capabilities: []});
  } else if (leftovers.length) {
    clusters.push({provider: null, models: leftovers, capabilities: []});
  }
  return clusters;
}

function atlasProviderClusterSize(cluster) {
  const modelCount = cluster.models.length;
  const capabilityCount = cluster.capabilities?.length || 0;
  const totalOrbit = modelCount + Math.min(capabilityCount, 6);
  return {
    w: totalOrbit > 5 ? 354 : 312,
    h: totalOrbit > 5 ? 278 : 238,
  };
}

function atlasProviderRequiredGroupHeight(items, group) {
  const clusters = atlasProviderClusterRows(items);
  const maxWidth = Math.max(280, group.w - (ATLAS_GROUP_MARGIN_X * 2));
  let rowWidth = 0;
  let rowHeight = 0;
  let height = ATLAS_GROUP_HEADER_Y + ATLAS_GROUP_MARGIN_X;
  clusters.forEach((cluster) => {
    const size = atlasProviderClusterSize(cluster);
    const nextWidth = rowWidth ? rowWidth + ATLAS_NODE_GAP_X + size.w : size.w;
    if (rowWidth && nextWidth > maxWidth) {
      height += rowHeight + ATLAS_NODE_GAP_Y;
      rowWidth = 0;
      rowHeight = 0;
    }
    rowWidth = rowWidth ? rowWidth + ATLAS_NODE_GAP_X + size.w : size.w;
    rowHeight = Math.max(rowHeight, size.h);
  });
  if (rowWidth) height += rowHeight;
  return Math.max(group.h, height + ATLAS_GROUP_MARGIN_X);
}

function atlasLayOutProviderGroup(items, group) {
  const clusters = atlasProviderClusterRows(items);
  const positions = {};
  const maxWidth = Math.max(280, group.w - (ATLAS_GROUP_MARGIN_X * 2));
  let x = group.x + ATLAS_GROUP_MARGIN_X;
  let y = group.y + ATLAS_GROUP_HEADER_Y;
  let rowHeight = 0;

  clusters.forEach((cluster) => {
    const size = atlasProviderClusterSize(cluster);
    if (x > group.x + ATLAS_GROUP_MARGIN_X && x + size.w > group.x + ATLAS_GROUP_MARGIN_X + maxWidth) {
      x = group.x + ATLAS_GROUP_MARGIN_X;
      y += rowHeight + ATLAS_NODE_GAP_Y;
      rowHeight = 0;
    }

    const centerX = x + (size.w / 2);
    const centerY = y + (size.h / 2);
    const providerSize = cluster.provider ? atlasNodeSize(cluster.provider) : {w: 204, h: 72};
    if (cluster.provider) {
      positions[cluster.provider.id] = {
        x: centerX - (providerSize.w / 2),
        y: centerY - (providerSize.h / 2),
        w: providerSize.w,
        h: providerSize.h,
      };
    }

    const orbitNodes = [...cluster.models];
    const radiusX = size.w * 0.36;
    const radiusY = size.h * 0.33;
    orbitNodes.forEach((node, index) => {
      const nodeSize = atlasNodeSize(node);
      const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / Math.max(1, orbitNodes.length));
      positions[node.id] = {
        x: centerX + Math.cos(angle) * radiusX - (nodeSize.w / 2),
        y: centerY + Math.sin(angle) * radiusY - (nodeSize.h / 2),
        w: nodeSize.w,
        h: nodeSize.h,
      };
    });

    (cluster.capabilities || []).forEach((node, index) => {
      const parent = cluster.models[index % Math.max(1, cluster.models.length)];
      const parentPos = positions[parent?.id] || {x: centerX, y: centerY, w: 0, h: 0};
      const nodeSize = atlasNodeSize(node);
      const side = index % 2 === 0 ? 1 : -1;
      positions[node.id] = {
        x: parentPos.x + parentPos.w + 8,
        y: parentPos.y + side * 34,
        w: nodeSize.w,
        h: nodeSize.h,
      };
    });

    x += size.w + ATLAS_NODE_GAP_X;
    rowHeight = Math.max(rowHeight, size.h);
  });
  return {positions, requiredHeight: Math.max(group.h, y - group.y + rowHeight + ATLAS_GROUP_MARGIN_X)};
}

function atlasRequiredGroupHeight(items, group) {
  if (group?.key === 'providers') return atlasProviderRequiredGroupHeight(items, group);
  const rows = atlasGroupRows(items, group);
  let y = group.y + ATLAS_GROUP_HEADER_Y;
  rows.forEach((row) => {
    const rowHeight = Math.max(...row.map((entry) => entry.size.h));
    y += rowHeight + ATLAS_NODE_GAP_Y;
  });
  return Math.max(group.h, y - group.y + ATLAS_GROUP_MARGIN_X);
}

function atlasLayOutGroup(items, group) {
  if (group?.key === 'providers') return atlasLayOutProviderGroup(items, group);
  const rows = atlasGroupRows(items, group);
  const positions = {};
  let y = group.y + ATLAS_GROUP_HEADER_Y;
  rows.forEach((row) => {
    const rowHeight = Math.max(...row.map((entry) => entry.size.h));
    let x = group.x + ATLAS_GROUP_MARGIN_X;
    row.forEach((entry) => {
      positions[entry.node.id] = {x, y, w: entry.size.w, h: entry.size.h};
      x += entry.size.w + ATLAS_NODE_GAP_X;
    });
    y += rowHeight + ATLAS_NODE_GAP_Y;
  });
  return {positions, requiredHeight: Math.max(group.h, y - group.y + ATLAS_GROUP_MARGIN_X)};
}

function atlasResolveGroups(nodes, groups) {
  const byGroup = new Map();
  nodes.forEach((node) => {
    const groupKey = groups[node.group] ? node.group : 'controller';
    if (!byGroup.has(groupKey)) byGroup.set(groupKey, []);
    byGroup.get(groupKey).push(node);
  });

  const resolvedGroups = Object.fromEntries(Object.entries(groups).map(([key, group]) => [key, {...group, key}]));
  byGroup.forEach((items, groupKey) => {
    resolvedGroups[groupKey].h = atlasRequiredGroupHeight(items, resolvedGroups[groupKey]);
  });
  atlasResolveGroupCollisions(resolvedGroups);

  const positions = {};
  byGroup.forEach((items, groupKey) => {
    const layout = atlasLayOutGroup(items, resolvedGroups[groupKey]);
    Object.assign(positions, layout.positions);
  });

  const extents = atlasGraphExtents(resolvedGroups, positions);
  return {groups: resolvedGroups, positions, width: extents.width, height: extents.height};
}

function atlasResolveGroupCollisions(groups) {
  const entries = Object.entries(groups).sort((a, b) => a[1].y - b[1].y || a[1].x - b[1].x);
  for (let pass = 0; pass < 8; pass += 1) {
    let moved = false;
    for (let i = 0; i < entries.length; i += 1) {
      const [, current] = entries[i];
      for (let j = 0; j < i; j += 1) {
        const [, previous] = entries[j];
        if (!atlasRectsOverlap(current, previous)) continue;
        current.y = previous.y + previous.h + 36;
        moved = true;
      }
    }
    if (!moved) break;
    entries.sort((a, b) => a[1].y - b[1].y || a[1].x - b[1].x);
  }
}

function atlasRectsOverlap(a, b) {
  return a.x < b.x + b.w + 20
    && a.x + a.w + 20 > b.x
    && a.y < b.y + b.h + 20
    && a.y + a.h + 20 > b.y;
}

function atlasGraphExtents(groups, positions) {
  const maxGroupX = Math.max(...Object.values(groups).map((group) => group.x + group.w), 0);
  const maxGroupY = Math.max(...Object.values(groups).map((group) => group.y + group.h), 0);
  const maxNodeX = Math.max(...Object.values(positions).map((pos) => pos.x + (pos.w || 204)), 0);
  const maxNodeY = Math.max(...Object.values(positions).map((pos) => pos.y + (pos.h || 72)), 0);
  return {
    width: Math.max(ATLAS_BASE_WIDTH, maxGroupX, maxNodeX) + ATLAS_MIN_CANVAS_PAD,
    height: Math.max(ATLAS_BASE_HEIGHT, maxGroupY, maxNodeY) + ATLAS_MIN_CANVAS_PAD,
  };
}
