# 2026-08-10 — Managed default workflow and `clay default`

`startup.json` now records a startup format version and whether its default is
managed by Clay. On startup, a managed older version receives the current
shipped default. Legacy files are migrated only when their `user` value exactly
matches a known former shipped default; unknown values are treated as custom.

Commands:

- `clay default` shows the workflow bare `clay` starts.
- `clay default set system chat` selects a searchable workflow.
- `clay default set -f ./workflow.json` selects an exact file.
- `clay default reset` restores the current shipped default and opts back into
  managed updates.

Writes are atomic. `set` marks the default as user-owned, so a later package
upgrade cannot mistake an intentional selection for an obsolete shipped value.
