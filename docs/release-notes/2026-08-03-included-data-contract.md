# 2026-08-03 · Included-data contract cleanup

## Changed

- Made the existing `includedData` default explicit in code: when the field is
  absent, handlers receive a shallow copy of the complete accumulated context.
- Preserved explicit filtering, aliases and dictionary dot paths such as
  `loop_id.action_id` and `workflow_id.action_id`.
- Corrected workflow documentation: nested workflows store their complete final
  context under the workflow action id; `workflow.outputKey` is accepted but
  currently ignored.
- Corrected loop documentation: the complete final iteration context is stored
  under the loop id, only the immediately previous iteration is carried
  forward, and no `loop_history` value is injected into executable context.
- Documented `loop.outputKey` as a run-log preview selector and `continueKey` as
  the existing termination control.
- Propagated parent `autoContext` recursively through nested workflows and loop
  iterations. Child instructions layer after inherited parent instructions.
- Reseeded engine globals (`__config__`, `__schema__`, and
  `__workflow_template__`) into nested workflows and iterations even when the
  container action filters ordinary inputs with `includedData`.

## Compatibility

No action field or result shape changed. Missing `includedData`, nested result
storage, loop self-reference, `continueKey`, `outputKey` and shallow merge
behavior remain compatible.

## Tests

Added regression coverage proving that the unfiltered action input is a copy,
so handler mutation cannot modify accumulated engine context.
