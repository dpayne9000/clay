# 2026-08-06 root-run LLM preflight

Every root workflow containing a `scramda2` or `humanDecision` action now
checks the configured model endpoint before executing its first action. A
missing server fails immediately through the existing `run.error` event and
explains the exact `llama-server --hf-repo ...` and `curl .../health` commands
needed to start and verify the configured model. Workflows without either
action skip the model-server check.

The check runs in the workflow engine, so CLI, daemon-launched, and Qt runs use
the same behavior. Nested workflows and loops do not repeat it. Reachable
OpenAI-compatible servers that return 404 or 405 for llama.cpp's `/health`
route remain supported.

Model requests and preflights now share endpoint precedence: `GOPHER_URL`,
then `provider.url` in Clay configuration, then
`http://127.0.0.1:8080`. No Telegram-specific startup behavior was added.
