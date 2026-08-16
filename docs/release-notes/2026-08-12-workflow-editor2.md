# 2026-08-12 — Workflow editor 2

Clay now includes an independent `workflows/system/editor2` workflow built only
from existing actions. The original editor remains available and unchanged.

Editor 2 does not inspect or copy another workflow as a design strategy. A
bounded construction loop selects one required file at a time from the user's
requirements, reads an existing target only for an explicit modification,
generates one path-bearing file response, applies it through the existing
`applyFileWrites` approval boundary, optionally runs Clay lint through
`runReplyCommands`, and carries the observed results into the next iteration.

Compact workflow protocol and action-contract data replace the original
editor's full-schema and tutorial injection. Explicit response limits reserve
input space for models with smaller context windows.

No action, engine, approval, lint, or filesystem implementation changed for
editor2. It is not yet the managed startup default, and runtime verification
remains pending.
