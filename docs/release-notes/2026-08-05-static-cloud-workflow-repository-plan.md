# Static cloud workflow repository plan — 2026-08-05

The cloud-workflow recovery plan now preserves `clay login`, `logout`,
`whoami`, `push`, and `pull`, including all existing command-line options. It
does not propose restoring the missing database application server.

The architecture was reopened after identifying that static package-tree
distribution does not supply the identity/session semantics needed by retained
`login`, `logout`, `whoami`, and per-user `push`. Static S3/HTTPS remains an
evaluated candidate for distribution, not an approved requirement or
implementation plan. Cognito remains rejected, but the documents no longer turn
that rejection into a ban on every possible identity-backed or hybrid design.

The current direction is now a single versioned Clay Cloud API backed by
MongoDB. That one boundary owns login/session identity, authorization, whoami,
complete workflow-unit push, and complete workflow-unit pull. S3/CloudFront
remains the release/public-download system instead of being forced to represent
private user identity. The API contract explicitly forbids client-supplied
Mongo queries or ownership fields and preserves F-31's local path, staging,
approval, and rollback requirements.

The plan now explicitly treats this as a new, unwritten API rather than an
adjustment to a surviving server. MongoDB stores each workflow/context/training
JSON object as a nested BSON document under its workflow unit; it does not store
the source file as a text blob. The client emits one consistent JSON formatting
style on pull and compares parsed objects so formatting normalization does not
create false workflow-change diffs.

The existing `api/` submodule was inspected as the server starting point. It is
a 78-file, 5,950-production-line NestJS/Mongoose application. Auth, users,
audit, throttling, health, and Mongo test infrastructure are reusable, but the
workflow module must be rewritten around complete BSON workflow units. Admin,
payments, cryptocurrency, Scramda CRUD, credits, templates, scheduling, Docker/
process execution, and system-user management can be removed. The task records
the exact security corrections, dependency reduction, expected 65–80% source
reduction, and a 6–10 working-day API estimate.

A minimal replacement was then written into the intentionally ignored local
`api2/` directory. It implements public ordinary-user signup, operator admin
bootstrap, RS256 access/refresh JWTs, Mongo-backed access blacklist, hashed
one-time refresh sessions, refresh-token family reuse revocation, logout,
whoami, and owner-scoped revision-controlled complete BSON workflow units. Its
routes cover only the cloud CLI network needs plus signup and health; it has no
payment, execution, scheduling, template, Docker, model, or generic Mongo API.

The initial dependency lock audit exposed 26 advisories, including a critical
native-bcrypt/node-tar chain. The dependency specification was changed to the
patched Nest 11 line, direct TypeScript compilation, and `bcryptjs`; the stale
lock was removed after regeneration was denied. The new dependency tree,
TypeScript build, e2e tests, Clay client migration, and deployment remain
unverified and incomplete.

The task now contains a code-traced inventory of every current cloud command,
option, helper, endpoint, local file, environment variable, startup side effect,
and failure path. The current implementation uses Python's standard library
`urllib`, not `requests`, `boto3`, or `pymongo`; has no dedicated cloud-command
tests; hardcodes credentials to `~/.clay/auth.json` instead of respecting
`CLAY_HOME`; and runs ordinary Clay user-data seeding before every cloud command.

A requirements audit now separates explicit user requirements, controls forced
by the requested security boundary, and unapproved product proposals. It also
records a blocking correction to the initial static format: Clay workflows are
multi-file directory units containing both workflow JSON and required context,
training, and goal data. Static publication must preserve and validate the
complete directory instead of rejecting every JSON file whose linter role is
`data`.

The F-31 record now points to this replacement design. No runtime cloud behavior
has changed yet, and the task document records five command, compatibility,
network, account-creation, and signing decisions that require approval before
implementation.
