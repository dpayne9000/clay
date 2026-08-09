# Coding2 file-write training and recovery

Coding2 now sends few-shot pairs as standard `user` / `assistant` chat
messages. Its acting pass demonstrates one canonical file form—the
workspace-relative path on the opening fence—and its review pass has separate
examples, including the expected no-change result.

Only verified writes are persisted to coding2 memory. Turns that wrote no
files do not create memory entries, and summaries no longer quote the raw model
reply where malformed fences could become future demonstrations.

`applyFileWrites` additionally recovers the common programming-language form
where the model puts a path on the first line inside the fence. Filename
recovery strategies are independent functions registered in
`BODY_PATH_READERS`, so tolerated syntaxes can be added or removed without
changing the rest of fence parsing. Text, Markdown, diff, and shell fences do
not use this inference.

Persisted memory can be cleared one namespace at a time:

```bash
clay memory purge system-coding2
```

The command deletes JSON entries in that namespace and leaves other memory
namespaces untouched.
