# Coding2 preliminary file selection

Coder2 now explicitly uses the workspace inventory and the initial user request
to select a small set of relevant existing files before its writing pass. Its
few-shot training demonstrates inferred reads for an implementation change and
a failing test instead of only demonstrating a direct "read this file" command.

The training also preserves the important no-read boundaries: coder2 does not
request a new destination that is absent from the inventory, and it does not
inspect the repository for a question that can be answered independently.

The existing `listWorkspace` and `<read_file>`/`serveFileReads` path is reused;
no workflow action or context field was added.
