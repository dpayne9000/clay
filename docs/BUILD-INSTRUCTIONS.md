# Clay release build instructions

This is the operator procedure for cutting a complete Clay release from the
source checkout, including the private Gopher snapshot, all eight distributable
archives, target testing, local promotion, website generation, and publication
to the Clay S3/CloudFront release site.

Do not skip a numbered gate. Commands in this document run from the repository
root. Replace values written inside angle brackets before running a command.

## 1. Confirm build-machine prerequisites

The build machine needs:

- Git access to the private `connectors/gopher` submodule;
- Python 3.11;
- enough free disk space for four CPython runtimes and the core/UI wheelhouses;
- AWS CLI v2 and the intended AWS profile for website creation or publication;
- separate macOS ARM64, macOS x86-64, Linux ARM64, and Linux x86-64 systems on
  which to execute the finished archives. WSL2 is an additional best-effort
  Linux compatibility check, not a ninth release target.

Create or refresh the repository development environment:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
```

The installed release does not need Git or access to the private Gopher
repository. Only the machine constructing release archives needs the submodule.

## 2. Prepare and verify the Gopher snapshot

Check out the exact Gopher commit recorded by the parent Clay commit:

```bash
git submodule update --init connectors/gopher
```

Copy the complete recursive Gopher runtime package into Clay's distributable
namespace:

```bash
.venv/bin/python -m scripts.build.sync_gopher
```

Review both identities before continuing:

```bash
git status --short
git diff --submodule=log -- connectors/gopher clay/vendor/gopher
```

If synchronization changed `clay/vendor/gopher`, review every changed file and
commit the Gopher submodule gitlink and vendored snapshot in the same Clay
commit. Do not delete or rewrite upstream files under `connectors/gopher`.

The release builder repeats a byte-for-byte, recursive comparison between
`connectors/gopher/gopher` and `clay/vendor/gopher`. It refuses a missing root
`__init__.py`, a missing or extra runtime file, or different file contents.

## 3. Set the Clay version and release notes

Set the release version only in `pyproject.toml` under `project.version`.
Clay's `--version` output is read from the installed distribution metadata
generated from that declaration.

Create or finish the release-notes file for this version under
`docs/release-notes/`, then reinstall the editable package and verify the
reported version:

```bash
.venv/bin/python -m pip install -e .
.venv/bin/clay --version
```

The output must be exactly:

```text
clay <version>
```

Commit the version, release notes, vendored Gopher snapshot, submodule gitlink,
and all intended application changes before building. The source commit is the
release's recorded source identity.

## 4. Run the source test suite

Run Clay's complete test convention:

```bash
.venv/bin/python -m clay.tests
```

Do not build a public candidate if any test fails. In particular, the Gopher
release tests verify recursive synchronization and require the wheel and source
archive to contain the complete vendored runtime package.

## 5. Require a clean, committed checkout

Inspect the parent worktree and submodule state:

```bash
git status --short
git submodule status connectors/gopher
```

`git status --short` must print nothing. The Gopher status must identify the
commit recorded by the parent repository without a leading `-`, `+`, or `U`.

Do not use `--allow-dirty` for a public release. That option exists only for
local development of the builder, labels the source revision dirty, and omits
the source archive. Dirty builds cannot be promoted.

## 6. Build the complete candidate matrix

Build both flavors for all four targets:

```bash
.venv/bin/python -m scripts.build --flavor all \
  --notes-file docs/release-notes/<release-note>.md
```

This creates a candidate under `dist/releases/<version>/` containing:

- `clay-<version>-macos-arm64-core.tar.gz`;
- `clay-<version>-macos-arm64-ui.tar.gz`;
- `clay-<version>-macos-x86_64-core.tar.gz`;
- `clay-<version>-macos-x86_64-ui.tar.gz`;
- `clay-<version>-linux-arm64-core.tar.gz`;
- `clay-<version>-linux-arm64-ui.tar.gz`;
- `clay-<version>-linux-x86_64-core.tar.gz`;
- `clay-<version>-linux-x86_64-ui.tar.gz`;
- `clay-<version>-source.tar.gz`;
- `release.json`; and
- `SHA256SUMS`.

`pyproject.toml` contains literal package, package-data, source-file, and
source-directory lists. The builder copies the source lists directly into
`dist/tmp-release-*`; it does not infer source membership from the package lists.
The source archive includes the listed runtime code, production configuration,
packaged skills, system workflows, templates, `README.md`, `pyproject.toml`, and
`setup.py`. It does not
contain `clay/tests/`, development workflows, workflow test fixtures, caches, or
top-level repository documentation. Files inside a listed source directory are
part of the source archive. The installed wheel specifies the same 15 runtime
packages and production data rather than discovering `clay.*` automatically.
Before building that wheel, the release builder copies only admitted source paths
into `dist/tmp-release-*` and runs setuptools there. It removes that temporary
tree afterward without modifying local `build/` or `clay.egg-info/`. Setuptools
is configured not to infer package data from generated source manifests.
Each target archive is constructed from its runtime, wheelhouse, Gopher license,
manifest, component inventory, and the single generated `install.py` entry point
it needs. No other repository root is admitted.
Release validation rejects any artifact path outside these allowlists.
For a `core` manifest, `install.py` installs `clay`; for a `ui` manifest, it
installs `clay[ui]` from the archive's offline wheelhouse so the packaged
PySide6, PySide6 Addons/Essentials, and shiboken6 wheels are installed.

The candidate's `release.json` initially contains `"stable": false`. Building
does not publish files and does not select the candidate as the website's latest
release.

The builder uses `scripts/build/targets.json` for target/runtime definitions
and `scripts/build/dependencies.lock.json` for packaged dependency versions.
Do not edit either file for an ordinary Clay source update.

## 7. Inspect the candidate and verify its checksums

Inspect the exact release directory:

```bash
ls -la dist/releases/<version>
```

On macOS, verify every listed archive from inside the directory:

```bash
cd dist/releases/<version>
shasum -a 256 -c SHA256SUMS
cd ../../..
```

On Linux, use `sha256sum -c SHA256SUMS` instead. Do not add arbitrary files to
the version directory: the release-contract validator admits only the manifest,
checksums, source archive, and exact eight target archives.

## 8. Test every target archive before promotion

A Mac M2 can assemble all eight archives, but it cannot establish that Linux or
Intel binaries execute correctly. Transfer each archive and `SHA256SUMS` to its
matching target, verify the checksum there, extract it, extract its bundled
runtime, and run its installer:

```bash
tar -xzf clay-<version>-<target>-<flavor>.tar.gz
cd clay-<version>-<target>-<flavor>
tar -xzf runtime/python.tar.gz
python/bin/python3 install.py
./clay --version
```

For every target, test the core archive and the UI archive. Confirm:

1. installation succeeds with no package-registry access;
2. `./clay --version` prints exactly `clay <version>`;
3. initial user data and system workflows seed correctly;
4. `./clay workflows` can list workflows;
5. the shipped workflows lint successfully;
6. one safe workflow completes through the CLI and `clayd`;
7. the Qt UI artifact starts and communicates through `clayd`; and
8. the installed Clay process imports and uses `clay.vendor.gopher` without the
   source checkout, Git, or the private submodule.

Record the system and result for every target in the release notes. Do not
promote if any advertised target has not been exercised or fails its applicable
checks.

## 9. Promote the tested local candidate

After all target checks pass, run:

```bash
.venv/bin/python -m scripts.build promote <version>
```

The command validates the complete release contract, prints the filenames and
SHA-256 values for all eight target archives, and asks whether those artifacts
passed the required target tests. Answer `y` only after comparing the displayed
files and hashes with the tested artifacts.

Promotion changes only the local `dist/releases/<version>/release.json`: it sets
`stable` to `true` and records `promotedAt`. It does not rewrite the tested
archives and does not upload anything.

## 10. Create the AWS release site once

Skip this section when `.clay-deploy.json` already records the intended site.
Before creating resources, confirm the intended AWS account and its CloudFront
pricing-plan status. Then run:

```bash
.venv/bin/python -m scripts.deploy --profile <profile> create \
  --bucket <globally-unique-bucket-name> \
  --region <region> \
  --accept-cloudfront-pricing
```

Review the printed AWS account, profile, region, and bucket before confirming.
The command creates a private encrypted/versioned S3 bucket, Block Public
Access, bucket-owner-enforced ownership, a CloudFront Origin Access Control,
the CloudFront distribution and bucket policy, then waits for deployment. It
writes the non-secret identifiers and the AWS-managed HTTPS URL to the ignored
`.clay-deploy.json` file.

The public site uses CloudFront HTTPS. It does not enable S3's public HTTP
static-website endpoint.

## 11. Generate the complete website locally

When `.clay-deploy.json` exists, the deployment plan uses its CloudFront URL and
rebuilds `dist/web` automatically:

```bash
.venv/bin/python -m scripts.deploy --profile <profile> plan
```

This command reads only promoted release records, validates each release,
replaces `dist/web` from a clean staging directory, and compares the resulting
objects with S3. It performs no AWS writes.

To generate `dist/web` without consulting AWS, run:

```bash
.venv/bin/python web/build.py \
  --base-url https://<distribution-domain>.cloudfront.net
```

Inspect at least these generated files:

```text
dist/web/index.html
dist/web/releases.html
dist/web/install.sh
dist/web/releases/releases.json
dist/web/releases/latest.json
dist/web/releases/latest.txt
dist/web/releases/<version>/release.json
dist/web/releases/<version>/SHA256SUMS
dist/web/releases/<version>/<release archives>
```

Confirm that `latest.json` and `latest.txt` identify the promoted version, the
release page lists its eight binaries and source archive, and every download URL
uses the intended CloudFront HTTPS base URL.

## 12. Review and publish the website

Run the no-write plan immediately before publication:

```bash
.venv/bin/python -m scripts.deploy --profile <profile> plan
```

Review every printed S3 upload or replacement. The tool refuses an unadmitted
local web file and refuses to overwrite an existing immutable versioned object
with different bytes.

Publish only after the plan is correct:

```bash
.venv/bin/python -m scripts.deploy --profile <profile> publish
```

The command rebuilds and revalidates `dist/web`, prints the plan again, and asks
for confirmation. It uploads immutable versioned release objects first, then
the mutable release index, latest pointers, installer, release pages, and main
page. Changed mutable paths receive a CloudFront invalidation.

## 13. Verify the live release

Open the printed CloudFront HTTPS URL and confirm the root page links to the
release page. Confirm that the release page lists the promoted version and that
its artifacts, manifest, checksums, and source archive download successfully.

On clean machines for every advertised target, install the public core release:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL \
  https://<distribution-domain>.cloudfront.net/install.sh | sh
```

Install the UI flavor where applicable:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL \
  https://<distribution-domain>.cloudfront.net/install.sh | sh -s -- --ui
```

Confirm `clay --version`, initial seeding, workflow listing/linting, one safe
CLI/clayd workflow, and UI startup again from the published installation. Verify
the downloaded archive hashes against the published `SHA256SUMS`, and confirm
that anonymous direct S3 access remains denied.

Record the final public URL and live verification results in the release notes.

## 14. Subsequent releases

For a later version, repeat sections 2 through 9, then sections 11 through 13.
Do not recreate the AWS site unless intentionally moving to a new bucket or
distribution.
