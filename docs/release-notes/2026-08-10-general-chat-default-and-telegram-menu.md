# 2026-08-10 — General chat default and Telegram workflow menu

Bare `clay` now seeds `workflows/system/chat/main.json` as the managed startup
workflow. Recognized former shipped defaults are migrated to it on upgrade.
Custom legacy values and defaults selected with `clay default set` remain
user-owned and are not overwritten.

General chat now receives Clay's registry-generated workflow template, a
concise operational guide, and selectively read files from the approved
project workspace. This lets it answer questions about current workflow syntax,
runtime capabilities, architecture, and the checked-out project from evidence.
It still performs no write or command action and does not claim those operations
occurred.

The shipped Telegram boot menu contains five general-purpose entries:

1. General chat — `workflows/system/chat/main.json`
2. Coding — `workflows/system/coding/main.json`
3. Build a workflow — `workflows/system/process_builder/main.json`
4. Code review — `workflows/templates/agents/code-review/main.json`
5. Web research — `workflows/templates/agents/web-researcher/main.json`

Verification covers the packaged startup value and exact Telegram menu. The
complete shipped workflow catalog lints clean: 284 files, 0 errors, 0 warnings.
