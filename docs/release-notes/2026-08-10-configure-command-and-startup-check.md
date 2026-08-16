# 2026-08-10 — `clay configure` and configuration checks

## What changed

- New subcommand: `clay configure`. Interactively sets `provider.url` and the
  `models` map in `~/.clay/config.json` — prompts for the server URL and a
  default model, then loops asking whether to define or update any other
  model profile (`code`, `chat`, `reports`, `orchestrator`, `telegram`, or a
  custom name), writing the result with the new `write_user_config()`.
  Finishes by re-checking the server and, if it's not reachable or not
  serving every configured model profile, printing the `llama-server` command
  to start it.
- New `clay/lib/config.write_user_config(cfg)` — the first writer
  `clay/lib/config.py` has ever had (everything else there is
  create-if-missing or read-only). Atomic: writes a `.tmp` file, then
  `os.replace()`s it over `config.json`, and clears the `lru_cache` so the
  next read picks it up.
- New `clay/lib/config_check.py` — `configuration_status()`, with the
  compatibility accessor `configuration_problem()`, run once per `clay` invocation
  (`clay/cli.py:cli()`), for every subcommand except `configure` itself.
  Its status contains a one-line reason, when present, and whether the problem
  is a loaded-model mismatch:
  1. `~/.clay/config.json` does not exist yet.
  2. The effective server URL (`GOPHER_URL`, when set, otherwise
     `provider.url`) is missing or not a valid `http(s)://host` URL.
  3. A model profile is blank, the server doesn't return a valid non-empty
     `/v1/models` listing, or that listing omits a configured model identity.
  llama.cpp normally reports a GGUF file path as its model ID. For Hugging
  Face cache paths, Clay decodes the exact `models--owner--repository` path
  component and compares `owner/repository` directly with the configured
  repository. It does not guess from GGUF filenames or quantization text.
- Each invocation checks `default` plus the explicit `modelProfile` values in
  the workflow about to run. Static `workflow` and `loop` child files are
  followed recursively, with cycle protection. Unrelated configured profiles
  are not compared. In-memory `run-json` payloads are scanned after parsing;
  because they have no workflow directory, child files cannot be resolved in
  advance.
- Connection and malformed-configuration problems remain advisory. An actual
  loaded-model mismatch stops before command execution and asks `Continue with
  the loaded model? [y/N]`; anything except an explicit yes stops. An
  event-socket daemon child does not ask again because its client made that
  decision before launching it.

## What this deliberately does not change

- `clay/run/preflight.py`'s existing hard block on `clay run`/`clay
  run-json` (unreachable server → `WorkflowFailure` with startup instructions)
  is untouched. Configuration and connection notices do not replace that
  preflight; only a confirmed loaded-model identity mismatch adds the earlier
  continue-or-stop decision.
- No "first run" flag or wizard-on-first-launch was added. Per direction,
  the trigger is the configuration state itself (missing file, unreachable
  server, or a served-model mismatch), checked fresh on every invocation,
  not a one-time first-run marker.
- QUICKSTART.md content is not printed or walked through by any of this —
  out of scope per explicit direction.

## Code references

- `clay/lib/config.py` — module docstring updated; `write_user_config()`
  added after `reload_config()`.
- `clay/lib/config_check.py` — new file; `_server_root()`,
  `startup_instructions()`, `configuration_status()`,
  `configuration_problem()`.
- `clay/cli.py` — `configure_cmd()` added before `_load_config()`; `configure`
  subparser registered before the `lint` subparser; the configuration check
  added in `cli()` right after `app_config.load_startup()`.
- Design questions and the full trace of `clay/lib/config.py`, `clay/cli.py`,
  and `QUICKSTART.md` that this was built from:
  `docs/tasks/completed/first-run-onboarding-and-config-command.md`.

## Verification

- Configuration-check unit coverage verifies exact Hugging Face cache identity
  decoding, workflow-scoped profiles including static children, missing
  requested profiles, malformed and empty model listings, blank profile values,
  the `GOPHER_URL` override, and fail-closed confirmation.
- The complete bundled workflow catalog lints clean: 283 files, 0 errors.
