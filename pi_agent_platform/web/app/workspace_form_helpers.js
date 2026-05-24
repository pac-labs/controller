// Shared form helpers for workspace/context configuration.
// Extracted from /ui/app.js during the v1.0.283 final app.js cleanup pass.
// Kept as classic-script globals so existing inline handlers and boot wiring continue to work.

function selectedMultiValues(fieldId) {
  const el = document.getElementById(fieldId);
  if (!el) return [];
  return Array.from(el.selectedOptions || []).map((o) => o.value).filter(Boolean);
}

function setSelectedMultiValues(fieldId, values = []) {
  const wanted = new Set(values || []);
  const el = document.getElementById(fieldId);
  if (!el) return;
  Array.from(el.options || []).forEach((o) => { o.selected = wanted.has(o.value); });
}
