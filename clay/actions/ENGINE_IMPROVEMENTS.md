# 20 engine / action improvements for smoother workflows

This is a narrower list than the workflow-editor one — not "here's what's
broken in one specific workflow," but "here's what's missing from the
engine and action library in general" that would make any workflow easier
to build and less fragile.

1. Right now, only two action types (`humanShell` and `writeSkill`) can
   conditionally skip themselves. Every other action always runs, no matter
   what. A generic way to say "skip this step if X" would remove a lot of
   awkward workarounds.
2. There's no way for the AI to actually choose and call a tool at runtime.
   You can ask it to describe what it wants to do, but nothing turns that
   description into a real action call. This is the missing piece for any
   kind of real assistant-with-tools workflow.
3. A `loop` or `workflow` step always points at one fixed file — you can't
   decide at runtime which sub-workflow to run next. Even letting it pick
   from a small approved list would open up a lot of designs that aren't
   possible today.
4. When a prompt asks the AI to reply with JSON, nothing actually checks
   that it did, or retries if it didn't. It's just a polite request. Any
   workflow that depends on structured output is fragile because of this.
5. If a piece of context a step expects just isn't there, nothing fails
   loudly — it just quietly shows up as a literal `{placeholder}` in
   whatever gets written or shown. A simple "this should exist, stop if it
   doesn't" check would catch mistakes way earlier.
6. The pattern for loading credentials from a config file is copy-pasted
   between actions instead of shared. Every new integration reinvents the
   same "read config, fall back to env vars, complain clearly if missing"
   logic.
7. Every `writeFile`/`readFile` call defaults to a folder called `output`
   unless you remember to override it. A workflow should be able to set
   that default once instead of every single file action needing to repeat
   it.
8. There's no way to tell `writeFile` "don't overwrite this if it already
   exists." Right now a bad filename guess can silently clobber something
   real.
9. Listing existing workflows or skills is done with raw shell commands
   like `ls workflows/`. That's fragile — depends on shell formatting and
   availability — when it could just be a proper action that returns clean,
   structured data.
10. There's no action that checks a generated workflow is actually valid
    before treating it as done — parsing the JSON and running it past the
    same checks the registry already has.
11. Similarly, there's no action that runs the existing lint checks
    automatically. Right now that's a separate manual step someone has to
    remember to run.
12. Nothing checks whether the context a step claims to need
    (`includedData`) is actually used anywhere in that step. It's easy to
    end up with a step that's wired up to receive something and then never
    actually reads it.
13. There's no safe way to preview what a generated workflow would do
    without actually running it for real.
14. When overwriting an existing file, there's no way to show a diff of
    what's changing — just the full new content, which makes it hard to
    tell what actually changed.
15. After generating a brand-new action type, nothing actually tries
    importing it to check it's not broken. It just gets registered and
    might fail the first time something tries to use it.
16. If we do build the "AI picks a tool" capability (#2), there should be
    one shared, well-tested "is this tool actually allowed" check — not
    something every workflow reimplements slightly differently, since
    getting that wrong is a real security problem, not just a bug.
17. Right now, generating multiple files in one go isn't really supported —
    most flows assume one file per turn. Anything that needs to produce a
    small set of related files has to work around that.
18. Once tool-calling exists, it'd be worth having one reusable "single
    conversational turn" building block, the same way there's already a
    shared research/review/approval building block.
19. When something fails validation or breaks, that reason mostly ends up
    in a log file a human has to go find. It'd be more useful if the
    workflow itself could see why something failed and react to it.
20. Id names aren't checked for consistency anywhere — nothing stops a step
    from being named with a space in it or mixed casing. A small lint rule
    would catch this automatically instead of relying on someone noticing
    in review.
