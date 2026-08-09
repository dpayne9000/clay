# 2026-08-05 — Obsolete cloud CLI disabled

The CLI no longer registers `login`, `logout`, `whoami`, `push`, or `pull`.
Their parser definitions remain commented beside an explanation of the required
`api2` migration, while the underlying modules and handlers remain available for
that work. This prevents the current release from calling the retired cloud API
or exposing the unsafe individual-file pull path.

A unit test requires all five names to be rejected by the real argparse parser.
Tests were not run per repository instructions.
