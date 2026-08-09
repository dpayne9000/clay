# Workflow lint alignment

The packaged workflow tree now passes `python -m clay.lint` without errors or
warnings.

The linter now models `includedData` using the same two names as runtime:

- the source root is checked in the caller (`alias=action.path` checks
  `action`);
- the alias, or the final dot-path component when there is no alias, is exposed
  to a called workflow.

Nested objects in JSON context files are valid and no longer produce a warning.
They are a supported part of the context contract and can be selected through
dot paths.

Workflow corrections include:

- replacing fields ignored by handlers (`maxTokens`, `urlKey`, literal `tags`,
  `loadContext.key`, and `shell.cwd`) with supported behavior;
- replacing nonexistent `loop_history` references with the iteration
  workflow's real action IDs, so each loop sees the immediately previous
  result without unbounded context growth;
- fixing aliases passed to nested workflows and correcting one invalid relative
  workflow path;
- removing an empty debug JSON file that could never be parsed;
- fixing missing editor/developer inputs without introducing new workflow
  fields.

`continueKey` and `outputKey` behavior are unchanged.
