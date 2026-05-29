# PAC Context Management Status

PAC 1.0.406 adds explicit runtime context pressure handling for long-running agent work.

## Implemented

- Context pressure tracking on every model loop iteration.
- Explicit checkpoint threshold at 65% of the active input budget.
- Explicit compaction threshold at 80% of the active input budget.
- Model-generated checkpoint summaries before compaction.
- Fallback checkpoint summaries when the configured model cannot summarize in time.
- Checkpoint summaries stored in task metadata and used as the rolling compaction anchor.
- Active-loop restore of the latest checkpoint summary when a resumed task has a saved summary.
- Per-session context budget metadata for UI display.
- Timeline events for:
  - `context_pressure`
  - `context_checkpoint_summary`
  - `context_checkpoint_summary_failed`
  - `context_checkpoint_restored`
  - existing `context_compacted` and `checkpoint_saved`

## Runtime behavior

The loop now manages context in this order before each model decision:

1. Estimate current message tokens.
2. Emit a context pressure event when the pressure level or percentage meaningfully changes.
3. At 65%, generate and persist a checkpoint summary.
4. Save a lightweight checkpoint for resume/recovery.
5. At 80%, compact older context using the checkpoint summary as the stable anchor.
6. Continue the loop with compacted messages instead of failing or silently truncating.

## Remaining work

- More precise tokenizer integration per provider/model.
- Dedicated context budget panel with historical pressure charts.
- User-selectable context thresholds per agent profile.
- Manual restore controls for selecting an older checkpoint.
- Cross-session checkpoint browsing and diffing.
