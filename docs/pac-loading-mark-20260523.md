# PAC loading mark

Version: 1.0.343

This pass replaces the old spinner-style loader with an animated PAC mark that follows the brand icon geometry.

## Animation behavior

The loader is intentionally sequential instead of rotational:

1. The icon starts dark.
2. The center blip appears.
3. The vertical line below the blip fills downward.
4. The six outer PAC mark elements light in order: bottom, lower-left, upper-left, top, upper-right, right.
5. The full mark stays lit briefly.
6. The full mark switches off at once and repeats.

## Assets

- `pi_agent_platform/web/assets/pac-loader.svg` is the animated transparent SVG used by the UI.
- `pi_agent_platform/web/assets/pac-loader-static.svg` is a fully lit transparent fallback/reference frame.
- `pi_agent_platform/web/assets/pac-loader-preview.gif` is a preview asset for design review and documentation.

The animation is implemented inside the SVG so callers can keep using the existing `.pac-loader` class without adding JavaScript.

## Accessibility

The SVG includes a title and description. It also respects `prefers-reduced-motion: reduce` by rendering a static fully lit mark instead of cycling the animation.
