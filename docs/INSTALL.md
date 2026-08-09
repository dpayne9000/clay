# Installing Clay

Clay is distributed directly from the Clay HTTPS release site. It is not
published to PyPI or another public Python package registry.

Supported platforms: macOS ARM64/x86-64, Linux ARM64/x86-64, and **Windows
through WSL2 only** — there is no native Windows package. On Windows, run the
commands below inside the WSL2 distribution and read [Windows](#windows) first.

Install the core CLI and daemon:

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

Download the core or UI archive for the operating system and CPU architecture
from the release page (`releases.html`), then run, substituting the version and
target:

```bash
tar -xzf clay-<version>-<target>-<flavor>.tar.gz
cd clay-<version>-<target>-<flavor>
tar -xzf runtime/python.tar.gz
python/bin/python3 install.py
./clay --version
```

The second extraction supplies the packaged Python 3.11 interpreter; no system
Python is required. `install.py` creates `venv/`, installs Clay from `wheels/`
without a package registry, and writes the `./clay` launcher beside it.

Run `install.py` in the directory the release will stay in. The virtual
environment and the `./clay` launcher record absolute paths, so a release that
is moved or renamed afterwards must have `python/bin/python3 install.py` run
again in its new location.

This procedure does not create `~/.local/bin/clay`. Invoke the extracted
`./clay`, or use the HTTPS installer for a versioned installation with a global
launcher.

## Installed layout

Program releases live under `~/.local/share/clay`; the launcher is created at
`~/.local/bin/clay`. Workflows, configuration, memory, logs, and directory
approvals live separately under `$CLAY_HOME`, normally `~/.clay`.

```text
~/.local/bin/clay                        symlink
→ ~/.local/share/clay/current/clay       symlink to the selected release
→ ~/.local/share/clay/releases/clay-<version>-<target>-<flavor>/clay
→ ~/.local/share/clay/releases/clay-<version>-<target>-<flavor>/venv/bin/clay
```

Releases are immutable and version-named. `current` selects one, so installing
another version does not overwrite the previous release directory.

## Windows

Clay runs on Windows through WSL2 only. There is no native Windows package:
the release matrix is macOS and Linux, and `clayd` uses a Unix domain socket,
which Windows does not provide.

Install inside the WSL2 distribution, not from PowerShell or Command Prompt.
WSL2 reports `Linux` and `x86_64` (or `aarch64` on an ARM Windows device), so
the standard installer selects the matching Linux archive:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL \
  https://get.clay.dev/install.sh | sh
```

Two differences from a native Linux installation:

**The Qt edition requires WSLg**, which ships with WSL2 on Windows 11 and on
Windows 10 build 19044 or later. Without it, `clay ui` fails when Qt
initializes its platform plugin. The core CLI and daemon do not need WSLg.

**`clayd` does not start automatically.** A WSL2 distribution is started and
stopped by the Windows host and has no Linux boot event, so neither the systemd
user unit nor the `@reboot` cron entry written by `clay daemon install` starts
it. Start it in the WSL2 shell:

```bash
clay daemon start
clay daemon status
```

Install into the WSL2 filesystem. Under `/mnt/c`, the launcher symlink and the
virtual environment's executable bits are not reliably preserved. The default
WSL2 `HOME` is already on the Linux filesystem.

## Make the `clay` command available

`clay` works from any directory when `~/.local/bin` is on `PATH`. The installer
does not edit shell startup files.

In the current shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
command -v clay
clay --version
```

Permanently, add the same line to `~/.zshrc` (zsh, the macOS default) or
`~/.bashrc` (Bash on Linux and WSL2):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then `source` that file or open a new terminal. Do not add a duplicate export.

## Repair the launcher

If the release exists but `~/.local/bin/clay` was deleted or replaced, rebuild
only the launcher symlink:

```bash
mkdir -p "$HOME/.local/bin"
ln -sfn "$HOME/.local/share/clay/current/clay" "$HOME/.local/bin/clay"
export PATH="$HOME/.local/bin:$PATH"
clay --version
```

Rerunning the HTTPS installer validates the selected release and recreates the
launcher. It does not overwrite `$CLAY_HOME`.

## Non-default directories

Set the installer variables on the `sh` process receiving the script, then add
the chosen `CLAY_BIN_DIR` to `PATH` instead of `~/.local/bin`:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL \
  https://get.clay.dev/install.sh | \
  CLAY_INSTALL_ROOT="$HOME/apps/clay" CLAY_BIN_DIR="$HOME/bin" sh
```

## Next

- Commands and first use: [README.md](../README.md)
- Editable checkout for contributors: [DEVELOPMENT.md](../DEVELOPMENT.md)
