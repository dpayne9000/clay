# Coding4 Reliable Final

Two semantic model calls:

1. `evidence_request`: reads only. It outputs `<read_file>` markers or `NO_ACTION`. It cannot output commands.
2. `agent_reply`: answers or writes the project. It may emit path-bearing file fences and optional pathless bash commands after seeing current files.

The earlier preflight-command behavior was removed because a file-list-only model can invent runners or commands before it has read the project. Optional execution now happens only in the main agent after current files are available.

The main training set is intentionally compact: nine examples, each teaching a distinct consumed output behavior rather than many variants of the same edit format.
