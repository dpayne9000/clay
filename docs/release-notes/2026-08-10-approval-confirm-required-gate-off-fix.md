# 2026-08-10 — approval gates, daemon workspace preflight, and contained writes

Clay now applies one consistent approval-gate polarity: an enabled gate asks an
attended user and refuses unattended execution; a disabled gate is explicit
advance approval. Busy state is restored after real prompts.

Daemon launches perform a visible workspace preflight before `clayd` starts.
CLI, Qt, and Telegram name the directory and missing read/write/command
capabilities. Approval is persisted to the narrow workspace grant and verified
before spawn. Both named and JSON daemon submissions fail closed, and the
server independently rechecks the grant.

`writeFile` and `writeCode` accept absolute destinations only when the resolved
path remains inside the approved root. Relative paths retain the same
containment check.

Related completed records:

- [F-35](../bugs/completed/F-35-approval-busy-indicator-not-restored.md)
- [F-36](../bugs/completed/F-36-approval-confirm-required-bypasses-gate-off.md)
- [F-44](../bugs/completed/F-44-daemon-spawn-skips-workspace-preflight.md)
- [F-45](../bugs/completed/F-45-writefile-rejects-absolute-paths-under-approved-root.md)
