# Coding Project Builder

The coding workflow follows the same plan-and-construct pattern as the workflow
editor:

`requirements -> PLAN.md -> one file per iteration -> write -> verify -> review -> update PLAN.md`

It selects a suitable project structure and technology from the request, then
generates source files, tests, manifests, configuration, documentation, and
supporting assets as required. Existing files are read only when the request
explicitly asks to modify them. Each successful construction step is recorded
before the next planned file is selected.

The final response is derived from the build record and reports only observed
writes and verification results.
