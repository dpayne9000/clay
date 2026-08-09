# Direct release distribution plan

Documentation now distinguishes Clay's proposed release design from its actual
installer state. No release builder, release CI workflow, checksummed archive,
or direct-download installer currently exists; `web/install.sh` still clones
and installs a source checkout.

Added `docs/tasks/direct-release-distribution.md` as the source-of-truth task for
a registry-free release pathway. It records the verified baseline, decisions
still requiring approval, artifact and installation contracts, package and
path prerequisites, one-builder implementation rule, offline wheelhouse,
integrity checks, atomic installation and upgrades, clean-artifact verification,
publication automation, documentation work, and final acceptance gate.

The active-task index links the new workstream. The older install/packaging
record now carries a prominent correction that its described builders and
artifacts remain proposed rather than implemented.

## Distribution decisions

The release host is Clay's own HTTPS web server. Releases will not depend on
GitHub Releases, PyPI, or another third-party release registry.

Each target archive will bundle a relocatable CPython 3.11 runtime and the
complete dependency wheelhouse. Installation therefore does not require Git,
system Python, or network dependency resolution. The exact Python patch release
and source checksum will be pinned per target in the release build inputs.

## S3 release-site plan

Added a dedicated plan for creating and deploying the release website. The
selected initial AWS route creates a new private S3 bucket behind a new
CloudFront distribution using CloudFront's default HTTPS hostname and
certificate. It requires no purchased/custom domain, Route 53 record, or ACM
certificate. Direct public S3 website hosting and Amplify Hosting are not used.

The planned Python deployment tool exposes `create`, `plan`, and `publish`,
orchestrates structured AWS CLI calls, builds the disposable site under
`dist/web`, generates human and JSON release indexes from verified local
manifests, uploads immutable releases before mutable pointers/pages, applies
appropriate cache metadata, refuses version replacement, and keeps the S3
bucket private through CloudFront Origin Access Control.

## Pipeline implementation

The plan is now implemented through the local-build/live-AWS boundary.

- `scripts.build` builds core and Qt UI archives for macOS ARM64/x86-64 and
  Linux ARM64/x86-64.
- CPython 3.11.15 standalone runtime URLs and upstream hashes are pinned for all
  four targets. Runtime tarballs are embedded unchanged, avoiding foreign
  filesystem extraction during cross-packaging.
- Runtime dependency versions are locked; PySide6 6.7.3 provides one consistent
  four-target UI baseline. Linux ARM64 UI consequently requires glibc 2.31.
- Gopher is packaged in the Clay wheel rather than imported through a checkout
  path injection.
- Corrected the initial multi-root setuptools configuration after an editable
  install proved that it exposed only `clay` and raised
  `ModuleNotFoundError: gopher`. Root `setup.py` now explicitly discovers both
  source trees, and release builds validate that the wheel contains both
  `clay/__init__.py` and `gopher/__init__.py`. A locally built wheel was
  inspected and contains both packages.
- Archives contain offline wheelhouses, a target installer, component records,
  source revision, target/flavor metadata, and begin with target verification
  explicitly false.
- The generated 0.1.0 matrix resolved and assembled all eight archives from the
  M2 build host. Runtime execution on Linux/Intel targets remains pending.
- `web/build.py` now creates `dist/web`, verifies release sizes/hashes, generates
  human and JSON release indexes, and substitutes the actual HTTPS deployment
  base URL into both page and installer.
- `web/install.sh` no longer clones Git or uses system Python. It enforces HTTPS,
  verifies SHA-256, extracts bundled CPython, installs with `--no-index`, checks
  `clay --version`, and atomically selects the completed release.
- `scripts.deploy` implements `create`, `plan`, and `publish` with AWS CLI v2.
  It creates private/versioned/encrypted S3, OAC, default-HTTPS CloudFront, and
  a source-ARN bucket policy; records non-secret state; refuses immutable
  collisions; uploads releases before pointers/pages; and invalidates only
  changed mutable paths.
- Focused release/deployment tests live under `clay/tests/release` and therefore
  participate in `python -m clay.tests`.
- `docs/RELEASE.md` records the build, site creation, planning, publication,
  installation, and remaining target/live-AWS verification commands.
- Root `BUILD.md` provides the short, ordered operator path from setting the
  version and running tests through rebuilding all eight artifacts, verifying
  each advertised target, previewing AWS changes, publishing, and checking the
  live installer. It distinguishes the one-time site creation step from the
  steps repeated for every program update.
- The source landing page now links to `releases.html`. Its new source template
  reuses the landing page's colors, typography, navigation, panels, and
  responsive behavior; the web builder fills both that root page and the
  existing `releases/index.html` compatibility page from the same verified
  release manifests.

Static parsing, command entry-point loading, `pyproject.toml` parsing, and
`git diff --check` pass. The repository test suite was not run, per repository
agent instructions.

One release-policy blocker was made explicit rather than guessed: the website
claims MIT, but Clay has no root license file. Gopher's MIT license is included
as a third-party notice; it is not treated as a license grant for Clay.

## 2026-08-04 pipeline audit record

Added `docs/tasks/release-pipeline-hardening.md` as the technical source of truth
for ten confirmed release-pipeline corrections: honest source identity,
candidate verification and stable promotion, atomic installation, complete
submodule-aware source archives, clean allowlisted web assembly, single version
identity, full release-contract validation, dependency wheel hashes,
restart-safe AWS creation, and end-to-end target acceptance.

Corrected stale status and premature completion claims in the distribution and
S3 tasks, linked the hardening queue from the MVP coordinator and active-task
index, and recorded that the existing local matrix is not publishable. No build,
installer, deployment code, AWS resource, or published object changed.

Validated every RPH item against the current functions and separated present
incorrect behavior from missing enforcement and final verification work. The
validation added two previously omitted failures: incremental matrix output can
mix old and new files in `dist/releases/<version>` after interruption, and the
manifest path written into `/releases/latest.json` resolves to the wrong URL
under ordinary document-relative URL resolution. It also records that current
version declarations agree and current artifact checksums pass, so RPH-06 and
RPH-07 are preventive enforcement gaps rather than claims of presently
mismatched version text or corrupted bytes.
