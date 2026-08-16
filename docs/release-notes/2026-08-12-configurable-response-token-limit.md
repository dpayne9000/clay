# 2026-08-12 — Configurable response token limit

Clay now stores the default model response limit in
`~/.clay/config.json` as `maxTokens`. New configurations use `4096`.

The `scramda2` action uses this configured value when its `max_tokens` field is
absent. An action-level `max_tokens` value overrides the configured default.

Both `clay configure` and its new `clay config` alias prompt for a positive
default response-token limit and save it atomically with the provider and
model-profile settings.

Curl-based release installations run the installed version's config migration.
The migration adds `maxTokens` to older configs without replacing existing
settings, and it preserves an existing `maxTokens` value. Runtime config reads
remain usable when the file is read-only by applying the built-in default in
memory.

Documentation now describes the command alias, setting precedence, migration
behavior, and the relevant runtime dependencies.
