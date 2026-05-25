// Mouse wheel zoom and drag-pan handling for the PAC Component Atlas viewport.

const DASHBOARD_ATLAS_PAN_KEY = 'pac-dashboard-atlas-pan-v1';
const ATLAS_INTERACTION_ZOOM_KEY = 'pac-dashboard-atlas-zoom-v1';
const ATLAS_MIN_ZOOM = 0.55;
const ATLAS_MAX_ZOOM = 1.35;
const ATLAS_ZOOM_STEP = 0.08;

function atlasClampZoom(value) {
  const next = Number(value);
  return Number.isFinite(next) ? Math.max(ATLAS_MIN_ZOOM, Math.min(ATLAS_MAX_ZOOM, next)) : 0.82;
}

function readAtlasPan() {
  try {
    const parsed = JSON.parse(localStorage.getItem(DASHBOARD_ATLAS_PAN_KEY) || 'null');
    if (parsed && Number.isFinite(parsed.x) && Number.isFinite(parsed.y)) return parsed;
  } catch (_) {}
  return {x: 0, y: 0};
}

function saveAtlasPan(x, y) {
  try { localStorage.setItem(DASHBOARD_ATLAS_PAN_KEY, JSON.stringify({x, y})); } catch (_) {}
}

function setAtlasPanValue(x, y) {
  const next = {x: Number.isFinite(Number(x)) ? Number(x) : 0, y: Number.isFinite(Number(y)) ? Number(y) : 0};
  saveAtlasPan(next.x, next.y);
  return next;
}

function setAtlasZoomValue(zoom) {
  const nextZoom = atlasClampZoom(zoom);
  try { localStorage.setItem(ATLAS_INTERACTION_ZOOM_KEY, String(nextZoom)); } catch (_) {}
  return nextZoom;
}

function applyAtlasTransform(viewport, pan, zoom) {
  const canvas = viewport?.querySelector('.atlas-canvas');
  if (!canvas) return;
  canvas.style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;
}

function atlasCanvasBounds(viewport) {
  const canvas = viewport?.querySelector('.atlas-canvas');
  if (!viewport || !canvas) return null;
  return {
    viewportWidth: Math.max(1, viewport.clientWidth || 1),
    viewportHeight: Math.max(1, viewport.clientHeight || 1),
    canvasWidth: Math.max(1, Number.parseFloat(canvas.style.width || canvas.dataset.atlasWidth || '1')),
    canvasHeight: Math.max(1, Number.parseFloat(canvas.style.height || canvas.dataset.atlasHeight || '1')),
  };
}

function applyAtlasViewportState(container, zoom, pan) {
  const viewport = container?.querySelector('.atlas-viewport');
  if (!viewport) return;
  const nextZoom = setAtlasZoomValue(zoom);
  const nextPan = setAtlasPanValue(pan?.x || 0, pan?.y || 0);
  const range = document.getElementById('atlasZoomRange');
  if (range) range.value = String(nextZoom);
  applyAtlasTransform(viewport, nextPan, nextZoom);
}

function centerAtlasViewport(container) {
  const viewport = container?.querySelector('.atlas-viewport');
  const bounds = atlasCanvasBounds(viewport);
  if (!bounds) return;
  const zoom = atlasClampZoom(localStorage.getItem(ATLAS_INTERACTION_ZOOM_KEY) || '0.82');
  const pan = {
    x: (bounds.viewportWidth - bounds.canvasWidth * zoom) / 2,
    y: Math.min(24, (bounds.viewportHeight - bounds.canvasHeight * zoom) / 2),
  };
  applyAtlasViewportState(container, zoom, pan);
}

function fitAtlasViewport(container) {
  const viewport = container?.querySelector('.atlas-viewport');
  const bounds = atlasCanvasBounds(viewport);
  if (!bounds) return;
  const nextZoom = atlasClampZoom(Math.min(ATLAS_MAX_ZOOM, Math.max(ATLAS_MIN_ZOOM, Math.min(
    (bounds.viewportWidth - 48) / bounds.canvasWidth,
    (bounds.viewportHeight - 48) / bounds.canvasHeight,
  ))));
  const pan = {
    x: (bounds.viewportWidth - bounds.canvasWidth * nextZoom) / 2,
    y: (bounds.viewportHeight - bounds.canvasHeight * nextZoom) / 2,
  };
  applyAtlasViewportState(container, nextZoom, pan);
}

function setupAtlasViewport(container, options = {}) {
  const viewport = container.querySelector('.atlas-viewport');
  const range = document.getElementById('atlasZoomRange');
  if (!viewport) return;
  let zoom = atlasClampZoom(options.zoom);
  let pan = readAtlasPan();
  let dragging = null;
  applyAtlasTransform(viewport, pan, zoom);

  viewport.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const beforeX = (ev.clientX - rect.left - pan.x) / zoom;
    const beforeY = (ev.clientY - rect.top - pan.y) / zoom;
    const direction = ev.deltaY < 0 ? 1 : -1;
    const nextZoom = setAtlasZoomValue(zoom * (1 + direction * ATLAS_ZOOM_STEP));
    pan = {
      x: ev.clientX - rect.left - beforeX * nextZoom,
      y: ev.clientY - rect.top - beforeY * nextZoom,
    };
    zoom = nextZoom;
    if (range) range.value = String(zoom);
    saveAtlasPan(pan.x, pan.y);
    applyAtlasTransform(viewport, pan, zoom);
    if (typeof options.onZoom === 'function') options.onZoom(zoom);
  }, {passive: false});

  viewport.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0 || ev.target.closest('.atlas-node')) return;
    ev.preventDefault();
    try { document.getSelection()?.removeAllRanges(); } catch (_) {}
    dragging = {x: ev.clientX, y: ev.clientY, panX: pan.x, panY: pan.y};
    viewport.classList.add('is-panning');
    viewport.setPointerCapture(ev.pointerId);
  });

  viewport.addEventListener('pointermove', (ev) => {
    if (!dragging) return;
    ev.preventDefault();
    pan = {x: dragging.panX + ev.clientX - dragging.x, y: dragging.panY + ev.clientY - dragging.y};
    saveAtlasPan(pan.x, pan.y);
    applyAtlasTransform(viewport, pan, zoom);
  });

  const finishDrag = (ev) => {
    if (!dragging) return;
    dragging = null;
    viewport.classList.remove('is-panning');
    try { viewport.releasePointerCapture(ev.pointerId); } catch (_) {}
  };
  viewport.addEventListener('pointerup', finishDrag);
  viewport.addEventListener('pointercancel', finishDrag);
}

function resetAtlasViewportState() {
  try { localStorage.removeItem(DASHBOARD_ATLAS_PAN_KEY); } catch (_) {}
}
