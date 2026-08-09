# 2026-08-06 workflow and Telegram output changes

Telegram workflow runs now display the same categories of information as
`clay run` without `-v`. The chat suppresses step headers, action-start lines,
skipped branches, outgoing model prompts, and INFO log narration. It continues
to show model answers, file changes and unified diffs, command results,
warnings, errors, and every question or approval that requires a response.

Workflow `visible` fields are unchanged. Hidden action events are still
removed by the engine, and the complete event stream remains in the run log.

## `system/clay` reads before editing and treats memory as background

The shipped `system/clay` workflow now lists the current project, selects the
small set of existing files needed for the current request, and reads them
before producing SEARCH/REPLACE edits. Its write instructions and training use
the same path-on-the-opening-fence convention as coding2 and coding3.

The current request now precedes retrieved memory in the final prompt. Memory
is explicitly non-authoritative background: it may provide a relevant user
preference or earlier decision, but cannot restart or authorize an older task.
Turns with no durable background now return `NO` from the existing summary
step and skip memory tagging and persistence, preventing transient requests
and “nothing happened” summaries from polluting later retrieval.
The incomplete `--dry-run` example was also replaced with a complete edit that
adds argument parsing instead of leaving part of the request to the user.

## Installed launcher and `PATH` instructions

The HTTPS installer now detects whether its launcher directory—normally
`~/.local/bin`—is present in the current `PATH`. When it is absent, installation
output prints the exact `export PATH=…` command and then tells the user to run
`clay --version`.

The README performs that setup and verification immediately after the install
command. `docs/INSTALL.md` now explains the immutable release directory,
`current` symlink, launcher symlink, persistent zsh and Bash/WSL2 setup,
launcher repair, and the supported custom installation variables.
