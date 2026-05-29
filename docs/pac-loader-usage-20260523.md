# PAC loader usage pass

Version: 1.0.344

This pass applies the animated PAC loading mark consistently across UI states that communicate loading, progress, or active agent thinking.

## Shared primitives

- `pi_agent_platform/web/app/ui_loading.js` exposes `PACLoading`, `pacLoaderIconHtml`, and `pacLoadingLineHtml` for classic-script modules.
- `pi_agent_platform/web/styles/pac-loading.css` defines the shared PAC loader icon, loading lines, loading blocks, status rows, and active thinking indicators.

## Applied surfaces

- Dashboard placeholder loading states.
- Provider, workspace, observe, source tree, directory access, and personal settings loading states.
- Uploading, queueing, endpoint-add, and endpoint-command progress messages.
- Endpoint job progress cards while jobs are queued, claimed, or running.
- Composer active thinking strip.
- Session thought/history rows that previously used the old small spinner.

## Notes

The existing animated SVG remains the canonical loader asset. The new helper keeps the icon usage centralized so follow-up surfaces can use the same PAC-branded loader without copying markup.
