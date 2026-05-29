# PAC Doom-Loop Detection Status

PAC now has a first-pass doom-loop detector for unproductive agent tool sequences.

## Implemented in 1.0.405

- Compact tool/outcome fingerprints are stored on each task in `doom_loop_history`.
- PAC detects repeated patterns such as:
  - three missing file reads across guessed paths,
  - the same failing tool outcome three times in a row,
  - the same short tool sequence repeated three times.
- When detected, PAC emits a `doom_loop_detected` event with a timeline card explaining the reason.
- PAC forces a read-only recovery action instead of letting the same failed pattern continue.
- Recovery rotates through:
  - `workspace_manifest`,
  - `find_code_paths`,
  - `list_files`.
- If the model keeps trying the same failing family after recovery started, PAC overrides that action with another discovery step.
- Session UI listens for `doom_loop_detected` events and surfaces them in the timeline/thinking summary.

## Current detector scope

The detector is intentionally conservative. It focuses on high-signal loops that have caused weak PAC/core behavior:

- guessed missing paths like `src/...`,
- repeated missing `read_file` or `read_file_chunk` calls,
- repeated denied/error tool outcomes,
- short repeated tool sequences.

## Still useful after live validation

- Add configurable thresholds per profile/session.
- Track model-level repetition such as repeated empty/narrative responses separately from tool repetition.
- Add Observe metrics for doom-loop frequency by tool/profile/model.
- Add more domain-specific recovery strategies for shell, git, package-manager, and LSP loops.
