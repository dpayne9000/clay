# 2026-08-04 — Private Gopher release snapshot

Clay now imports Gopher from `clay.vendor.gopher`. The complete Gopher project
continues to exist as the `connectors/gopher` upstream submodule; no upstream
project data was removed.

Release builds now require the complete recursive vendored runtime package to
match the checked-out build-machine input exactly. Maintainers can synchronize a reviewed
upstream update with `python -m scripts.build.sync_gopher`. Clay wheels require
the namespaced vendor package, and clean-release validation now detects
untracked files that would otherwise be excluded from `git archive`.

The release documentation now labels the current pipeline as candidate-only.
`BUILD.md` no longer instructs maintainers to set `--stable` before target
verification, and publication remains explicitly blocked until the promotion,
contract-validation, installer-recovery, dependency-integrity, web-staging, and
AWS-recovery gates are implemented and verified.

The release-hardening queue was then re-audited against the installed wheel and
current scripts. The audit added confirmed installed-path failures in clayd,
memory, skills, saved web records, email/alert configuration, Qt model profiles,
and `clay docs`. It removed the obsolete proposal to splice the full Gopher
submodule into Clay's source archive, separated source-suite execution from
installed-artifact smoke testing, and made exact dependency-wheel hash locking
optional for the MVP while retaining required dependency-license work.
The audit also retains the release blocker that the website claims Clay is MIT
licensed while the repository currently contains no Clay root license.

Installed-release corrections now make clayd spawn the installed `clay` console
script, move memory/skill/saved-site paths under `CLAY_HOME`, combine packaged
and user skill reads while protecting packaged files, and load application
configuration through Clay's config module. Installation completes inside a
temporary sibling directory before final placement. Release construction and
website generation use complete replacement directories, website copying uses
the exact manifest/checksum/archive set, and deployment rejects extra files.
Runtime version reporting now comes from installed distribution metadata, and
an explicit `scripts.build promote VERSION` operation separates target testing
from website generation and AWS publication.
New immutable artifact manifests no longer contain a permanent
`verifiedOnTarget: false` field; the release-level `promotedAt` records the
operator's post-test promotion without rewriting tested archives.

Gopher synchronization now mirrors nested packages and runtime data instead of
only top-level Python modules. Wheel and source-archive validation require that
complete recursive runtime tree. These checks run only while constructing
installers; installed Clay imports the bundled `clay.vendor.gopher` package and
has no Git or private-repository dependency.

The recursive Gopher snapshot test fixtures now include the package's required
root `__init__.py`. This lets the stale-snapshot test reach and identify its
intentional `chat.py` content mismatch while the exact-snapshot fixture passes
the package-validity guard.

`docs/BUILD-INSTRUCTIONS.md` is now the complete release-operator runbook. It
covers build-machine prerequisites, private Gopher submodule synchronization,
versioning, source tests, clean-checkout requirements, the full eight-archive
candidate build, checksum inspection, per-target execution, local promotion,
one-time S3/CloudFront creation, clean website generation, deployment planning,
publication ordering, and live installation verification.

Release packaging now explicitly excludes the repository's top-level `web/`,
`dist/`, and `scripts/` directories. Wheel, target-archive, and source-archive
validation rejects those roots if packaging configuration later attempts to
include them. Target releases retain only their required generated `install.py`
entry point, not the build/deployment script tree.

UI release installation now requests the packaged `clay[ui]` extra. The UI
archives already contained the pinned PySide6, PySide6 Addons/Essentials, and
shiboken6 wheels, but the installer previously requested only `clay`, leaving
those optional wheels unused. The missing-Qt CLI message now directs release
users to the UI release and reserves the editable-install command for source
developers; it no longer implies that Clay is available from a public package
registry.

The Qt run log now renders `workspace.approve` as three explicit controls:
**Approve & Remember**, **Allow Once**, and **Refuse**. They submit the existing
`y`, `o`, and `n` responses through the unchanged workflow-input channel. Other
workflow questions continue to use the free-text answer field.

The clayd prompt path now preserves that behavior across every Qt run surface.
The editor converts clayd's separate `prompt_id` envelope into the log panel's
input-request event, while the daemon terminal and process-dashboard cards use
the same prompt ID to select their button rows. Previously the editor ignored
the separate prompt envelope and the dashboard always displayed free text.

The root README is now a concise public installation and usage guide for the
direct HTTPS core/UI releases. Private source-checkout setup, editable installs,
tests, model-server development, Gopher synchronization, and release-work links
moved to `DEVELOPMENT.md`. Its adjacent setup commands distinguish core
`pip install -e .` from Qt development with `pip install -e '.[ui]'`.
The installation document now describes the same direct release path instead
of retaining the obsolete source-only installation claim.

A code-backed security audit now records seven additional marketplace blockers:
unsigned same-origin release verification, fail-open Telegram authorization,
ambient-permission daemon IPC, cloud-pull path traversal, network-action SSRF
gaps, untrusted online content reaching execution sinks, and unhashed dependency
wheel inputs. `docs/tasks/security-trust-boundary-audit.md` orders the concrete
corrections and verification gates; no issue is marked fixed by documentation.

Telegram authorization now fails closed. The persistent Telegram action
requires `TELEGRAM_ALLOWED_USERS` or `TELEGRAM_ALLOWED_CHATS`, validates every
configured ID, and supplies the allowlists to the bridge before polling starts.
The bridge itself also rejects an empty authorization policy.
The shipped Telegram workflow explains how to obtain `from.id` and `chat.id`
through Bot API `getUpdates`, how to configure one or both lists, and why the
token must remain outside repository files. Authorization tests cover messages,
edited messages, commands, and callback queries.
The callback authorization test now mocks Telegram's required callback
acknowledgement, keeping the unit suite offline instead of sending the fixture
token to the live Bot API.
