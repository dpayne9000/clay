# Process Builder

Human-guided workflow generator based on deterministic workflow patterns.

`workflow_template.json` is the structural source of truth: the generator may use only action types and fields present there.

The user first selects a proven topology, then configures paths, model responsibility, command permission, and training strength. The final model renders the approved pattern; it is not allowed to invent architecture.

Included starter patterns:
1. revise a configured file from prompt;
2. create a file from prompt;
3. read files and answer;
4. revise files then optionally execute a command;
5. generate new files from prompt;
6. two-stage evidence selection then coding.
