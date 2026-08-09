# Developing Clay

This document is for contributors working from a source checkout. End users
install Clay from its HTTPS release site as described in [README.md](README.md).

## Requirements

- Python 3.11 or newer;
- Git with submodule support;
- macOS or Linux; or Windows through WSL2;
- an OpenAI-compatible model server for workflows containing AI actions.

On WSL2, keep the checkout in the Linux filesystem rather than under `/mnt/c`.
The Qt application requires WSLg.

## Check out the source

```bash
git clone --recurse-submodules <private-clay-repository-url>
cd <clay-checkout>
```

If the checkout already exists but Gopher is not initialized:

```bash
git submodule update --init connectors/gopher
```

The private Gopher source remains under `connectors/gopher`. Clay imports the
reviewed runtime snapshot under `clay/vendor/gopher`; ordinary execution does
not import from the submodule.

## Create the development environment

```bash
python3.11 -m venv .venv
```

For CLI, daemon, engine, and core-action development:

```bash
.venv/bin/python -m pip install -e .
```

For Qt UI development, use the adjacent UI-extra command instead:

```bash
.venv/bin/python -m pip install -e '.[ui]'
```

The UI form installs the same editable `clay` distribution plus the pinned
PySide6 dependency. There is no separate public `clay-ui` package.

The generated console script is `.venv/bin/clay`. Either invoke that exact path
or link it into a directory already on `PATH`:

```bash
ln -s "$PWD/.venv/bin/clay" ~/.local/bin/clay
```

## Verify the checkout

```bash
.venv/bin/clay --version
.venv/bin/clay workflows
.venv/bin/python -m clay.tests
```

For a UI environment, also verify the optional dependency and start Qt:

```bash
.venv/bin/python -c "import PySide6; print(PySide6.__version__)"
.venv/bin/clay ui
```

The repository instructions require changes to participate in the standard
`python -m clay.tests` discovery convention. Do not create a separate test
runner for a feature.

## Local model server

AI actions use the bundled Gopher adapter to contact an OpenAI-compatible HTTP
server. The default is `http://127.0.0.1:8080`:

```bash
export GOPHER_URL=http://127.0.0.1:8080
```

Start the model server using its own documented command and model files before
running a workflow that contains AI actions.

## Update the vendored Gopher runtime

Only perform this when intentionally updating the Gopher submodule revision:

```bash
git submodule update --init connectors/gopher
.venv/bin/python -m scripts.build.sync_gopher
git diff --submodule=log -- connectors/gopher clay/vendor/gopher
```

Review every copied file. Commit the submodule gitlink and the corresponding
`clay/vendor/gopher` snapshot together. Do not delete upstream source,
documentation, examples, metadata, or Git history from `connectors/gopher`.

## Development commands

```bash
.venv/bin/clay lint <workflow-or-path>
.venv/bin/clay dryrun <workflow-or-path>
.venv/bin/clay run <workflow-or-path>
.venv/bin/clay daemon start
.venv/bin/clay daemon status
.venv/bin/clay ui
```

Use `--project-dir PATH` when a workflow should operate somewhere other than
the shell's current directory. Directory access remains subject to Clay's
workspace approval boundary.

## Release work

Use [docs/BUILD-INSTRUCTIONS.md](docs/BUILD-INSTRUCTIONS.md) for the complete
candidate build, target testing, promotion, website generation, and publication
procedure. Do not substitute ad-hoc wheel or upload commands for that runbook.
