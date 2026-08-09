# 40 potential improvements — workflows & construction

This came from actually reading the editor's workflow files line by line
(`workflows/system/editor/main.json` and `iteration.json`), plus
`clay/lib/context.py` and `clay/actions/agent/loop_actions.py` to check how
context and loops really behave. Part 1 is a list of real, confirmed bugs —
things that are broken right now, not guesses about what might be broken.
That's why the editor doesn't actually produce a working workflow today.

(`clay/actions/NEW_ACTIONS.md` is a separate, older note about how to
register a new action type — it's stale but it's a different topic, so I
left it alone and made this a new file.)

## Part 1 — what's actually broken in the editor right now (fix these first)

1. In `main.json`, the boot step reads the tutorial file from a hardcoded
   path: `~/projects/platformCLI/workflows/system/editor/`. Two problems —
   it's spelled wrong (capital "CLI", but the real folder is
   `platformCli`), and it's tied to one specific person's home directory
   instead of being relative to the project. It should just be resolved
   relative to the workflow's own folder.
2. The prompt that asks the model to generate a workflow (`workflow_template`
   in `iteration.json`) contradicts itself. It asks for "a json scaffolding
   script" that prints `CREATED: <path>` for each file — that sounds like
   an executable script. Then in the same prompt it says "Return ONLY the
   raw json workflow" — that's just data, not a script. The model can't do
   both, so whichever way it interprets this, something downstream breaks.
3. The very next step, `write_workflow`, is supposed to take that generated
   content and do something with it — it lists `workflow_template` as
   available context, but the actual prompt text never mentions it. I
   checked the literal string. So this step just asks the model to write a
   workflow again from nothing, ignoring everything decided so far. That's
   a wasted AI call, and it means the file that eventually gets saved isn't
   actually connected to the build plan.
4. Right after that, the `build` step takes whatever the model wrote and
   tries to run it as Python code. But the earlier prompt told the model to
   output raw JSON, not Python — and JSON's `true`/`false`/`null` aren't
   valid Python. So if the model does what it was told, this step just
   throws an error. This is probably the main reason nothing actually gets
   built.
5. When the generated workflow file finally gets saved, the `writeFile`
   step doesn't say where to save it relative to — so it falls back to the
   default, which is a folder called `output`. That means new workflows end
   up at `output/workflows/custom/...` instead of the real
   `workflows/custom/` folder the whole conversation is supposedly building
   toward. I checked — `workflows/custom/` doesn't even exist yet in this
   repo.
6. The review step shows the human a prompt that includes
   `{scaffolding_script}` — but nothing in the entire file ever produces
   anything with that name. It's a leftover reference to something that
   must have existed at some point and got renamed or removed. Right now it
   just shows up blank/broken on screen.
7. Also in the review step — the human types "APPROVE" or types their
   concerns, and that answer gets saved... but nothing later ever reads it.
   Approving or rejecting literally doesn't change what happens next.
8. Worse, by the time the human even sees that review prompt, the file has
   already been generated and saved in an earlier step. So even if the
   approval step worked, it's in the wrong place to stop anything.
9. The way the loop knows when to stop asking the user for more work
   depends on a separate AI call replying with a plain "YES" or "NO." This
   happens to work today only because the code that checks it happens to
   lowercase everything before comparing. But nothing forces the model to
   actually say "yes" or "no" — a small prompt tweak later could quietly
   break the exit condition and nobody would notice until the loop refuses
   to stop.
10. One of the step IDs is literally `"check save"` — with a space in it.
    Every other ID in the codebase is one word or camelCase. It's a small
    thing but it's inconsistent and awkward to reference from anywhere else.

## Part 2 — the real gap: nothing checks the work before it's "done"

Right now the action library is mostly generic helpers (read a file, write
a file, run a shell command). There's nothing that actually validates or
double-checks a generated workflow before it gets treated as finished. That
gap is why bugs like #3 and #6 above can exist without anyone noticing.

11. An action that validates a generated workflow — parses the JSON and
    runs it through the same validation the registry already has — before
    it's ever written to disk. Catch a broken generation before it becomes
    a broken file.
12. An action that runs the same lint checks (`clay/lint.py`) automatically
    against generated content, instead of relying on someone remembering to
    run lint by hand afterward.
13. An action that checks whether every id a generated action references
    (via `includedData`) was actually produced somewhere earlier in the
    same file. This alone would have caught bug #6.
14. A "dry run" action that lets the assistant preview what a generated
    workflow would actually do, without really running it, before
    committing to writing it out.
15. When overwriting an existing workflow file, show the human an actual
    diff of what's changing, instead of reprinting the whole thing. Makes
    the review step meaningful again.
16. Give `writeFile` the same "skip if this resolves to a certain value"
    option that `humanShell` and `writeSkill` already have. That's the
    actual fix for bugs #7 and #8 — it lets the write itself depend on
    whether the human approved.
17. The build-plan prompt already asks "what files need to be created,"
    implying there could be more than one. But right now the pipeline only
    ever writes exactly one file per turn. Need something that loops over
    however many files the plan calls for and writes each one.
18. A safer wrapper around the "create a new action type" action that
    actually tries importing what it just wrote, so a broken generated
    action doesn't just sit there registered and silently fail the next
    time someone tries to use it.
19. A shared, reusable "is this tool allowed" check — something any future
    "let the AI pick a tool" workflow can use instead of everyone building
    their own version of the same trust boundary.
20. The editor currently pastes the entire raw schema (about 27,000
    characters) straight into its prompt. There's already a much smaller,
    purpose-built version of this exact thing — the `workflows/registry/`
    example tree, about 9x smaller — that was built specifically to replace
    this. The editor just never got switched over to use it.

## Part 3 — bigger gaps in what the engine can do at all

21. There's no general way to conditionally skip a step. Only `humanShell`
    and `writeSkill` support "skip this if the value is empty" — everything
    else always runs. That's the single biggest limitation that came up
    while designing things this session.
22. The "let the AI decide which tool to call" action we designed earlier
    this session doesn't exist yet — it needs to be built. Without it,
    there's no safe way for a workflow to let the model choose actions at
    runtime.
23. You can't tell a `loop` or `workflow` step which file to run based on
    something decided at runtime — the file path is always fixed ahead of
    time. Even a limited version of this (pick from an approved list) would
    open up a lot of dynamic workflows.
24. A reusable "one conversational turn" building block, alongside the
    research/review/human building blocks that already exist, once the
    tool-calling design from this session actually gets built.
25. Right now, when a prompt asks the model to reply with strict JSON, it's
    just... asking nicely. Nothing actually checks the reply is valid JSON
    or retries if it isn't. That would make every place we rely on
    structured output a lot less fragile.
26. A simple guard that fails loudly if some expected piece of context is
    missing, instead of quietly leaving something like `{key}` printed
    literally into a file or prompt.
27. The pattern for loading credentials from a config file (used in
    `email_actions.py`, and planned for the Victron action) is copy-pasted
    logic. Worth pulling into one shared helper instead of every
    credentialed action reimplementing it slightly differently.
28. Let a workflow set a default save location once, instead of every
    single `writeFile`/`readFile` call needing to remember to override it.
    This is exactly what caused bug #5, and it's an easy mistake to repeat.
29. An option to make `writeFile` refuse to overwrite a file that already
    exists, so a bad filename guess during generation can't silently
    clobber something already built.
30. Turn "list the existing workflows/skills" into real actions instead of
    raw shell commands (`ls workflows/`). Less fragile, and doesn't depend
    on shell formatting.

## Part 4 — testing and visibility gaps

31. A test that actually runs the editor end to end with a fixed request
    and checks the result is a valid file. This alone would have caught
    every bug in Part 1 automatically instead of needing someone to read
    the JSON by hand.
32. When a generation fails validation, that reason should show up
    somewhere the assistant itself can see and react to — not just buried
    in a log file a human has to go find.
33. A way to re-run just the "build and save" part of a turn against a
    previously generated plan, without re-asking the human anything —
    useful for iterating on the editor's own prompts.
34. Double check the existing tests for the `workflows/registry/` example
    tree still pass — the editor's tutorial content depends on that staying
    accurate.
35. A lint check that catches the general shape of bug #3 — a step that
    lists some context as available but never actually uses it in its
    prompt.

## Part 5 — docs and process

36. Write a dedicated task doc for the Part 1 fixes so each one can be
    reviewed and landed on its own, instead of one giant patch.
37. Actually update `clay/actions/NEW_ACTIONS.md` — right now it's one
    stale line pointing at a file (`runWorkflows.py`) that doesn't even
    match how actions get registered anymore.
38. Update `docs/plans/redesign/current.puml` once any of this actually
    lands, per the standing instruction to keep it current.
39. Write down the failure modes from Part 1 somewhere (wrong save
    location, dead placeholder, wrong language) so the next person
    debugging a workflow doesn't have to re-trace all of this from scratch.
40. Write down the id-naming convention (no spaces, consistent case) and
    have lint enforce it, instead of relying on people noticing in review.
