# 2026-08-08 — Installed `clay` command runs again

## Fixed

### The launcher looked for the virtual environment beside its symlink

An installation performed by `web/install.sh` produced a `clay` command that
failed immediately:

```text
/Users/<user>/.local/bin/clay: line 2: /Users/<user>/.local/bin/venv/bin/clay: No such file or directory
```

`scripts/build/install_release.py` wrote the release launcher as
`exec "$(dirname "$0")/venv/bin/clay" "$@"`. The installer reaches that
launcher through the `~/.local/bin/clay` symlink, and a POSIX shell sets `$0`
to the path the script was invoked as rather than the file it resolves to, so
`dirname "$0"` named `~/.local/bin` and the launcher searched for a virtual
environment that has never existed there.

The launcher now records the console script's absolute path:

```sh
#!/bin/sh
exec "/home/<user>/.local/share/clay/releases/clay-<version>-<target>-<flavor>/venv/bin/clay" "$@"
```

Release directories are version-named and are not moved after installation;
upgrades move the `current` symlink, so the recorded path stays valid for the
life of the release. `launcher_script()` rejects a relative path or one that
cannot be safely double-quoted rather than emitting a launcher that would
misparse.

### The virtual environment recorded a staging directory that was then deleted

`web/install.sh` extracted the release into
`releases/.<name>.installing.XXXXXX/<name>`, ran `install.py` there, and moved
the finished tree to `releases/<name>` afterwards. `python -m venv` writes
absolute paths at creation time, so after the move every `venv/bin/*` shebang
and the `home`, `executable`, and `command` keys of `venv/pyvenv.cfg` still
named the deleted staging directory:

```text
#!/Users/<user>/.local/share/clay/releases/.clay-0.1.0-macos-arm64-core.installing.<id>/…/venv/bin/python
```

`install.py`'s `clay --version` check passed because it ran before the move.
The installer now moves the extracted release to its final directory first and
runs `install.py` there, so the virtual environment is created at its permanent
path. Installation remains atomic from a user's perspective because no release
is selectable until the `current` symlink is moved after a successful install,
and the existing signal trap now removes a destination whose installation
failed.

## Documentation

- `docs/INSTALL.md` — the installed path chain now shows the versioned release
  directory that the launcher records, and the manual archive-local procedure
  states that a release directory moved after `install.py` runs must have
  `install.py` run again.
- `scripts/QUICKREBUILD.md` — new: build and install one local target archive
  to replace a broken installation, and the manual AWS CLI sequence for
  withdrawing a published version from S3, which `scripts.deploy` has no
  subcommand for.
- `docs/tasks/installer-launcher-absolute-path.md` — new: reproduction, both
  defects, and the fix.

## Tests

- `clay/tests/release/test_install_release.py` — `LauncherScriptTest`: the
  launcher records the absolute console-script path, contains neither `$0` nor
  `dirname`, and rejects relative and unquotable targets.
- `clay/tests/release/test_web_installer.py` — `WebInstallerOrderingTest`: the
  release reaches its final directory before `install.py` runs, a failed
  installation removes the destination, and `current` is moved only after a
  successful installation.

Run: `.venv/bin/python -m clay.tests`

## Upgrade note

`install.py` ships inside each release archive, so an installation performed by
an earlier archive cannot be repaired from this repository. Rebuild and
reinstall using `scripts/QUICKREBUILD.md`.
