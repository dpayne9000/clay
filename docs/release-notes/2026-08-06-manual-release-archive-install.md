# 2026-08-06 manual release archive installation documentation

The README and installation guide now place direct-download installation
commands immediately after the HTTPS installer commands. The documented path
extracts the target archive, extracts its bundled Python 3.11 runtime, runs
`install.py` with that interpreter, and verifies the resulting archive-local
`clay` launcher.

The documentation distinguishes this archive-local installation from
`install.sh`: only the HTTPS installer creates the standard versioned program
directory and `~/.local/bin/clay` launcher.
