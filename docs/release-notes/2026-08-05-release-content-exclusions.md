# 2026-08-05 — Release content exclusions

Clay release admission now uses positive allowlists instead of a list of known
repository directories to exclude.

The source builder now specifies the runtime code directories, exact production
configuration files, five packaged skill directories, system workflows,
template workflows, `README.md`, `pyproject.toml`, and `setup.py`. Python tests,
development workflows, workflow test fixtures, caches, and top-level repository
documentation are absent. Files inside a directory named by the source template
remain part of the source archive.

`pyproject.toml` contains the authoritative installed-package list, installed
package-data list, and separate literal source template. Setuptools and wheel
validation consume the installed lists; source construction consumes the source
template. Unit tests require the exact package list and reject broad
development/test data patterns.

The first allowlisted build exposed stale setuptools state: the existing
`build/lib/` tree and `clay.egg-info/SOURCES.txt` still named tests, development
workflow data, top-level Gopher modules, and bytecode from the old discovery
configuration. Release wheel construction now copies only admitted sources into
`dist/tmp-release-*`, builds there, and removes only that temporary directory.
It never modifies the working tree's generated packaging directories.
Setuptools also has `include-package-data = false` so only the declared data list
is eligible.

Source construction now uses two literal lists under
`pyproject.toml:[tool.clay-release.source]`: `files` and `directories`. The
builder copies those entries into `dist/tmp-release-*`; both wheel construction
and the source archive use that staged tree. Source-file validation performs a
direct exact-file or listed-directory-prefix check. The rejected derived
package graph, parent-directory exceptions, filesystem type probing, and
per-member generated sets were removed.

Target archives admit only the bundled runtime archive, flat wheelhouse, Gopher
license, installer, manifest, and component inventory. Validation rejects an
unexpected file even when it is placed beneath an otherwise valid directory.
New repository directories therefore remain outside releases automatically.

The generated target installer remains a single top-level `install.py`; it does
not expose the repository's `scripts/` tree. Website generation and deployment
remain separate: only files admitted by the release manifest plus the explicit
site files can enter `dist/web` or the S3 upload plan.

Tests were not run, following the repository instruction that the user executes
`python -m clay.tests`.
