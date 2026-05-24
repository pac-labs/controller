// Collision-aware PAC Component Atlas layout helpers.

const ATLAS_NODE_GAP_X = 28;
const ATLAS_NODE_GAP_Y = 20;
const ATLAS_GROUP_MARGIN_X = 22;
const ATLAS_GROUP_HEADER_Y = 58;
const ATLAS_MIN_CANVAS_PAD = 80;
const ATLAS_BASE_WIDTH = 2240;
const ATLAS_BASE_HEIGHT = 1560;

function atlasNodeSize(node) {
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

function atlasRequiredGroupHeight(items, group) {
  const rows = atlasGroupRows(items, group);
  let y = group.y + ATLAS_GROUP_HEADER_Y;
  rows.forEach((row) => {
    const rowHeight = Math.max(...row.map((entry) => entry.size.h));
    y += rowHeight + ATLAS_NODE_GAP_Y;
  });
  return Math.max(group.h, y - group.y + ATLAS_GROUP_MARGIN_X);
}

function atlasLayOutGroup(items, group) {
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

  const resolvedGroups = Object.fromEntries(Object.entries(groups).map(([key, group]) => [key, {...group}]));
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
