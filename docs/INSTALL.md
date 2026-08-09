# Installing Clay

Clay is distributed directly from the Clay HTTPS release site. It is not
published to PyPI or another public Python package registry.

Install the core CLI and daemon on macOS or Linux:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL \
  https://get.clay.dev/install.sh | sh
```

Install the Qt desktop edition:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL \
  https://get.clay.dev/install.sh | sh -s -- --ui
```

## Install a downloaded release archive manually

After downloading the correct core or UI archive for the operating system and
CPU architecture from `releases.html`, replace the example filename below and
run:

```bash
tar -xzf clay-0.1.2-macos-arm64-core.tar.gz
cd clay-0.1.2-macos-arm64-core
tar -xzf runtime/python.tar.gz
python/bin/python3 install.py
./clay --version
```

The second extraction supplies the packaged Python 3.11 interpreter required
by `install.py`; no system Python installation is required. `install.py`
creates `venv/` in the extracted release directory, installs Clay and its
dependencies from `wheels/` without accessing a package registry, and writes
the `./clay` launcher beside `install.py`.

Run `install.py` where the release directory will stay. The virtual
environment's script interpreters and the `./clay` launcher record absolute
paths, so a directory that is moved or renamed afterwards must have
`python/bin/python3 install.py` run again in its new location.

This archive-local procedure does not move the release under
`~/.local/share/clay` and does not create `~/.local/bin/clay`. Keep the extracted
directory and invoke its `./clay` launcher. Use the HTTPS installer when the
standard versioned installation and global launcher are desired.

The installer detects macOS/Linux and ARM64/x86-64, downloads the matching
archive, checks it against the release's `SHA256SUMS`, and installs the bundled
CPython runtime and offline wheelhouse. WSL2 is supported as a Linux environment
on a best-effort basis; the Qt edition requires WSLg.

Program releases live under `~/.local/share/clay`, and the launcher is created
at `~/.local/bin/clay`. User workflows, configuration, memory, logs, and
directory approvals live separately under `$CLAY_HOME`, normally `~/.clay`.

The installed path chain is:

```text
~/.local/bin/clay                        symlink
→ ~/.local/share/clay/current/clay       symlink to the selected release
→ ~/.local/share/clay/releases/clay-<version>-<target>-<flavor>/clay
→ ~/.local/share/clay/releases/clay-<version>-<target>-<flavor>/venv/bin/clay
```

The release launcher records that final path literally. A POSIX shell reports
the invoked path in `$0`, which is the `~/.local/bin/clay` symlink, so a
launcher that derived its target from `$0` would look for the virtual
environment beside the symlink instead of inside the release.

Versioned releases remain under `~/.local/share/clay/releases/`. The `current`
symlink selects one of them, so installing another version does not overwrite
the previous release directory.

## Make the `clay` command available

`clay` can be invoked from any working directory when `~/.local/bin` is on
`PATH`. The installer does not edit shell startup files. It reports the exact
launcher path and prints a corrective command when that directory is absent
from the current `PATH`.

Enable it in the current shell and verify the installed command:

```bash
export PATH="$HOME/.local/bin:$PATH"
command -v clay
clay --version
```

For zsh, including the default interactive shell on current macOS, add this
line to `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then reload it with `source "$HOME/.zshrc"` or open a new terminal.

For Bash on Linux or WSL2, add the same line to `~/.bashrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then reload it with `source "$HOME/.bashrc"` or open a new terminal. If that
export already exists, do not add a duplicate.

## Repair the launcher

If the release exists but `~/.local/bin/clay` was deleted or replaced, rebuild
only the launcher symlink:

```bash
mkdir -p "$HOME/.local/bin"
ln -sfn "$HOME/.local/share/clay/current/clay" "$HOME/.local/bin/clay"
export PATH="$HOME/.local/bin:$PATH"
clay --version
```

Rerunning the HTTPS installer also validates the existing selected release and
recreates the launcher. It does not overwrite `$CLAY_HOME` user data.

To use non-default program or launcher directories, set the installer variables
for the `sh` process receiving the downloaded script:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL \
  https://get.clay.dev/install.sh | \
  CLAY_INSTALL_ROOT="$HOME/apps/clay" CLAY_BIN_DIR="$HOME/bin" sh
```

In that case, add the selected `CLAY_BIN_DIR` to `PATH`; the default
`~/.local/bin` instructions no longer apply.

For command examples and first use, continue with [README.md](../README.md).
Contributors installing an editable private checkout must use
[DEVELOPMENT.md](../DEVELOPMENT.md), which documents both:

```bash
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install -e '.[ui]'
```
