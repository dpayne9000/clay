"""Install/uninstall clayd as a system service.

Supported platforms and strategies:

  macOS           launchd user agent     ~/Library/LaunchAgents/com.busbar.clayd.plist
  Linux (systemd) systemd user unit      ~/.config/systemd/user/clayd.service
  FreeBSD         daemon(8) + cron       @reboot crontab entry
  Linux (no user  cron fallback          @reboot crontab entry
   systemd, e.g.
   RHEL/CentOS 7)

Linux distro coverage:
  Ubuntu 20.04+, Debian 11+, Fedora 38+, RHEL/CentOS 9  -- systemd 240+, Type=exec
  RHEL/CentOS 8                                          -- systemd 239, Type=simple
  RHEL/CentOS 7                                          -- user systemd compiled out, cron fallback
"""

import os
import platform
import shutil
import subprocess
import sys
import textwrap


# ── Shared paths ──────────────────────────────────────────────────────────────

def _python_path():
    """Resolve the python interpreter to bake into the service file."""
    here = _working_dir()
    for candidate in [
        os.path.join(here, '.venv', 'bin', 'python'),
        os.path.join(here, 'TEMPENV', '.env', 'bin', 'python'),
    ]:
        if os.path.exists(candidate):
            return os.path.realpath(candidate)
    return os.path.realpath(sys.executable)


def _working_dir():
    """The platformCLI directory (cwd for the daemon)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _log_path():
    return os.path.expanduser('~/.clay/clayd.log')


def _pid_path():
    return os.path.expanduser('~/.clay/clayd.pid')


# ── macOS launchd ─────────────────────────────────────────────────────────────

_LAUNCHD_LABEL = 'com.busbar.clayd'
_LAUNCHD_DIR = os.path.expanduser('~/Library/LaunchAgents')
_LAUNCHD_PLIST = os.path.join(_LAUNCHD_DIR, f'{_LAUNCHD_LABEL}.plist')


def _launchd_plist_content():
    python = _python_path()
    cwd = _working_dir()
    log = _log_path()
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{_LAUNCHD_LABEL}</string>
            <key>ProgramArguments</key>
            <array>
                <string>{python}</string>
                <string>-m</string>
                <string>clay.daemon.server</string>
            </array>
            <key>WorkingDirectory</key>
            <string>{cwd}</string>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <dict>
                <key>SuccessfulExit</key>
                <false/>
            </dict>
            <key>StandardOutPath</key>
            <string>{log}</string>
            <key>StandardErrorPath</key>
            <string>{log}</string>
            <key>EnvironmentVariables</key>
            <dict>
                <key>PATH</key>
                <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
            </dict>
        </dict>
        </plist>
    """)


def _install_launchd():
    os.makedirs(_LAUNCHD_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(_log_path()), exist_ok=True)

    if os.path.exists(_LAUNCHD_PLIST):
        subprocess.run(['launchctl', 'unload', _LAUNCHD_PLIST],
                       capture_output=True)

    with open(_LAUNCHD_PLIST, 'w') as f:
        f.write(_launchd_plist_content())
    print(f'Wrote {_LAUNCHD_PLIST}')

    result = subprocess.run(['launchctl', 'load', _LAUNCHD_PLIST],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f'launchctl load failed: {result.stderr.strip()}', file=sys.stderr)
        return False

    print(f'Loaded launchd agent: {_LAUNCHD_LABEL}')
    _print_config()
    print(f'\nclayd will start on login and restart on crash.')
    return True


def _uninstall_launchd():
    if not os.path.exists(_LAUNCHD_PLIST):
        print(f'Not installed (no plist at {_LAUNCHD_PLIST})')
        return False

    result = subprocess.run(['launchctl', 'unload', _LAUNCHD_PLIST],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f'launchctl unload warning: {result.stderr.strip()}', file=sys.stderr)

    os.unlink(_LAUNCHD_PLIST)
    print(f'Removed {_LAUNCHD_PLIST}')
    print(f'Unloaded launchd agent: {_LAUNCHD_LABEL}')
    return True


def _status_launchd():
    if not os.path.exists(_LAUNCHD_PLIST):
        return 'not installed'
    result = subprocess.run(
        ['launchctl', 'list', _LAUNCHD_LABEL],
        capture_output=True, text=True)
    if result.returncode != 0:
        return 'installed, not loaded'
    out = result.stdout
    for line in out.splitlines():
        stripped = line.strip().rstrip(';')
        if '"PID"' in stripped:
            parts = stripped.split('=')
            if len(parts) == 2:
                pid = parts[1].strip().rstrip(';')
                return f'installed, running (pid {pid})'
    for line in out.splitlines():
        if '"LastExitStatus"' in line:
            parts = line.strip().rstrip(';').split('=')
            if len(parts) == 2:
                code = parts[1].strip().rstrip(';')
                if code != '0':
                    return f'installed, not running (last exit: {code})'
    return 'installed, not running'


# ── Linux systemd ─────────────────────────────────────────────────────────────

_SYSTEMD_UNIT_NAME = 'clayd.service'
_SYSTEMD_DIR = os.path.expanduser('~/.config/systemd/user')
_SYSTEMD_UNIT = os.path.join(_SYSTEMD_DIR, _SYSTEMD_UNIT_NAME)


def _systemd_version():
    """Return the installed systemd version as an int, or 0 if unavailable."""
    try:
        result = subprocess.run(
            ['systemctl', '--version'],
            capture_output=True, text=True)
        # First line: "systemd 252 (252.22-1ubuntu1)"
        first = result.stdout.strip().splitlines()[0]
        for token in first.split():
            if token.isdigit():
                return int(token)
    except Exception:
        pass
    return 0


def _systemd_unit_content():
    python = _python_path()
    cwd = _working_dir()
    ver = _systemd_version()

    # Type=exec (systemd 240+) catches exec failures at start time.
    # Fall back to Type=simple for RHEL 8 (systemd 239) and older.
    svc_type = 'exec' if ver >= 240 else 'simple'

    return textwrap.dedent(f"""\
        [Unit]
        Description=clayd - clay workflow process manager
        After=network.target

        [Service]
        Type={svc_type}
        ExecStart={python} -m clay.daemon.server
        WorkingDirectory={cwd}
        Environment=PYTHONPATH={cwd}
        Environment=PATH=/usr/local/bin:/usr/bin:/bin
        Restart=on-failure
        RestartSec=5
        StartLimitBurst=5
        StartLimitIntervalSec=60

        [Install]
        WantedBy=default.target
    """)


def _check_user_systemd():
    """Verify systemctl --user works. Returns (ok, error_message).

    Two things can prevent user systemd from working:
      1. XDG_RUNTIME_DIR not set (no login session -- e.g. bare su/sudo)
      2. D-Bus user session unavailable (RHEL 7 compiled it out, or
         dbus-user-session not installed on Debian/Ubuntu headless)

    Note: clayd itself does NOT use D-Bus -- it uses a plain Unix socket.
    D-Bus is only required by 'systemctl --user' to talk to the user's
    systemd instance.
    """
    xdg = os.environ.get('XDG_RUNTIME_DIR', '')
    if not xdg:
        return False, (
            'XDG_RUNTIME_DIR is not set. User systemd requires a login session.\n'
            'Ensure you are in a proper login session (not su/sudo).\n'
            'If connecting via SSH, use: ssh -t user@host'
        )
    result = subprocess.run(
        ['systemctl', '--user', 'status', '--no-pager'],
        capture_output=True, text=True)
    stderr = result.stderr
    # returncode 1 is fine (no active units), only check for bus errors
    if 'Failed to connect to bus' in stderr:
        # Give distro-specific advice
        distro = _detect_linux_distro()
        if distro in ('centos', 'rhel'):
            fix = 'sudo yum install dbus-x11, then log out and back in'
        elif distro in ('debian', 'ubuntu'):
            fix = 'sudo apt install dbus-user-session, then log out and back in'
        elif distro == 'fedora':
            fix = 'sudo dnf install dbus-daemon, then log out and back in'
        else:
            fix = 'install dbus-user-session (or equivalent), then re-login'
        return False, (
            f'Cannot connect to user D-Bus session.\n'
            f'Fix: {fix}\n'
            f'Or ensure you are in a proper login session (not su/sudo).'
        )
    return True, ''


def _detect_linux_distro():
    """Best-effort distro detection from os-release. Returns lowercase name."""
    try:
        with open('/etc/os-release') as f:
            content = f.read().lower()
        for name in ('ubuntu', 'debian', 'fedora', 'centos', 'rhel', 'rocky',
                     'alma', 'opensuse', 'arch', 'manjaro'):
            if name in content:
                return name
    except FileNotFoundError:
        pass
    return 'unknown'


def _install_systemd():
    if not shutil.which('systemctl'):
        print('systemctl not found', file=sys.stderr)
        return _install_cron_fallback('systemctl not available')

    ver = _systemd_version()

    # RHEL/CentOS 7: systemd 219, user services compiled out
    if ver > 0 and ver < 230:
        distro = _detect_linux_distro()
        print(f'systemd {ver} detected ({distro}) -- user services not supported',
              file=sys.stderr)
        return _install_cron_fallback(f'systemd {ver} too old for user services')

    ok, err = _check_user_systemd()
    if not ok:
        print(f'User systemd not available:\n{err}', file=sys.stderr)
        return _install_cron_fallback('user systemd session unavailable')

    os.makedirs(_SYSTEMD_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(_log_path()), exist_ok=True)

    with open(_SYSTEMD_UNIT, 'w') as f:
        f.write(_systemd_unit_content())
    print(f'Wrote {_SYSTEMD_UNIT}')

    subprocess.run(['systemctl', '--user', 'daemon-reload'],
                   capture_output=True)

    result = subprocess.run(['systemctl', '--user', 'enable', _SYSTEMD_UNIT_NAME],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f'systemctl enable failed: {result.stderr.strip()}', file=sys.stderr)
        return False

    result = subprocess.run(['systemctl', '--user', 'start', _SYSTEMD_UNIT_NAME],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f'systemctl start failed: {result.stderr.strip()}', file=sys.stderr)
        return False

    svc_type = 'exec' if ver >= 240 else 'simple'
    print(f'Enabled and started systemd user service: {_SYSTEMD_UNIT_NAME}')
    print(f'  Type:    {svc_type} (systemd {ver})')
    _print_config()
    print(f'  Log:     journalctl --user -u {_SYSTEMD_UNIT_NAME}')

    # Linger check
    user = os.environ.get('USER', '')
    has_linger = (
        user and os.path.exists(f'/var/lib/systemd/linger/{user}')
    )
    if not has_linger:
        print(f'\nNote: enable linger so clayd survives logout:')
        print(f'  sudo loginctl enable-linger {user}')
    else:
        print(f'\nclayd will start on login and restart on crash.')

    return True


def _uninstall_systemd():
    if not os.path.exists(_SYSTEMD_UNIT):
        print(f'Not installed (no unit at {_SYSTEMD_UNIT})')
        return False

    if shutil.which('systemctl'):
        subprocess.run(['systemctl', '--user', 'stop', _SYSTEMD_UNIT_NAME],
                       capture_output=True)
        subprocess.run(['systemctl', '--user', 'disable', _SYSTEMD_UNIT_NAME],
                       capture_output=True)

    os.unlink(_SYSTEMD_UNIT)

    if shutil.which('systemctl'):
        subprocess.run(['systemctl', '--user', 'daemon-reload'],
                       capture_output=True)

    print(f'Removed {_SYSTEMD_UNIT}')
    print(f'Stopped and disabled systemd user service: {_SYSTEMD_UNIT_NAME}')
    return True


def _status_systemd():
    if not os.path.exists(_SYSTEMD_UNIT):
        return 'not installed'
    if not shutil.which('systemctl'):
        return 'installed (systemctl not found)'
    result = subprocess.run(
        ['systemctl', '--user', 'is-active', _SYSTEMD_UNIT_NAME],
        capture_output=True, text=True)
    state = result.stdout.strip()
    if state == 'active':
        pid = _systemd_main_pid()
        if pid:
            return f'installed, running (pid {pid})'
        return 'installed, running'
    return f'installed, {state}'


def _systemd_main_pid():
    """Get main PID, compatible with systemd 219+ (no --value flag)."""
    result = subprocess.run(
        ['systemctl', '--user', 'show', _SYSTEMD_UNIT_NAME,
         '--property=MainPID'],
        capture_output=True, text=True)
    out = result.stdout.strip()
    # "MainPID=12345" format
    if '=' in out:
        pid = out.split('=', 1)[1].strip()
    else:
        pid = out
    return pid if pid and pid != '0' else None


# ── FreeBSD daemon(8) + cron ─────────────────────────────────────────────────

_CRON_MARKER = '# clayd-autostart'


def _cron_command():
    """The cron @reboot command line for starting clayd."""
    python = _python_path()
    cwd = _working_dir()
    log = _log_path()
    pid = _pid_path()

    if platform.system() == 'FreeBSD' and shutil.which('daemon'):
        # FreeBSD daemon(8): -r restarts on crash, -P writes supervisor pidfile
        return (
            f'@reboot cd {cwd} && PYTHONPATH={cwd} '
            f'/usr/sbin/daemon -r -P {pid} -o {log} '
            f'{python} -m clay.daemon.server {_CRON_MARKER}'
        )
    # Generic cron: simple restart loop with backoff
    return (
        f'@reboot cd {cwd} && PYTHONPATH={cwd} '
        f'nohup {python} -m clay.daemon.server '
        f'>> {log} 2>&1 & echo $! > {pid} {_CRON_MARKER}'
    )


def _get_crontab():
    """Return current user crontab lines, or empty list."""
    try:
        result = subprocess.run(['crontab', '-l'],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.splitlines()
    except FileNotFoundError:
        pass
    return []


def _set_crontab(lines):
    """Write lines as user crontab."""
    content = '\n'.join(lines) + '\n'
    proc = subprocess.run(['crontab', '-'],
                          input=content, capture_output=True, text=True)
    return proc.returncode == 0


def _install_cron_fallback(reason=''):
    """Install clayd as a @reboot cron job. Used on FreeBSD and old Linux."""
    if not shutil.which('crontab'):
        print('crontab not found -- cannot install cron fallback', file=sys.stderr)
        return False

    os.makedirs(os.path.dirname(_log_path()), exist_ok=True)

    existing = _get_crontab()
    # Remove any existing clayd entry
    cleaned = [l for l in existing if _CRON_MARKER not in l]
    cleaned.append(_cron_command())

    if not _set_crontab(cleaned):
        print('Failed to update crontab', file=sys.stderr)
        return False

    method = 'daemon(8) + cron' if shutil.which('daemon') else 'cron'
    if reason:
        print(f'({reason} -- using {method} fallback)')
    print(f'Installed @reboot cron entry for clayd')
    _print_config()
    print(f'  Log:     {_log_path()}')

    if platform.system() == 'FreeBSD' and shutil.which('daemon'):
        print(f'\nclayd will start on boot and restart on crash (via daemon(8)).')
    else:
        print(f'\nclayd will start on boot. No automatic restart on crash.')
        print(f'For crash recovery, consider running inside a process supervisor.')

    return True


def _uninstall_cron():
    """Remove clayd @reboot cron entry."""
    existing = _get_crontab()
    cleaned = [l for l in existing if _CRON_MARKER not in l]
    if len(cleaned) == len(existing):
        return False  # nothing to remove
    _set_crontab(cleaned)
    print(f'Removed clayd @reboot cron entry')
    return True


def _status_cron():
    """Check if clayd has a @reboot cron entry."""
    for line in _get_crontab():
        if _CRON_MARKER in line:
            return 'installed (cron @reboot)'
    return 'not installed'


# ── Platform dispatch ─────────────────────────────────────────────────────────

def _detect_platform():
    """Returns 'macos', 'linux', 'freebsd', or raises."""
    system = platform.system()
    if system == 'Darwin':
        return 'macos'
    if system == 'Linux':
        return 'linux'
    if system == 'FreeBSD':
        return 'freebsd'
    raise RuntimeError(f'Unsupported platform: {system}')


def _print_config():
    """Print common config info."""
    print(f'  Python:  {_python_path()}')
    print(f'  WorkDir: {_working_dir()}')


def install():
    """Install clayd as a system service. Returns True on success."""
    plat = _detect_platform()
    if plat == 'macos':
        return _install_launchd()
    elif plat == 'freebsd':
        return _install_cron_fallback()
    else:
        return _install_systemd()


def uninstall():
    """Uninstall clayd system service. Returns True on success."""
    plat = _detect_platform()
    removed = False
    if plat == 'macos':
        return _uninstall_launchd()
    elif plat == 'freebsd':
        return _uninstall_cron()
    else:
        # On Linux, might have systemd unit, cron fallback, or both
        if os.path.exists(_SYSTEMD_UNIT):
            removed = _uninstall_systemd()
        cron_removed = _uninstall_cron()
        if not removed and not cron_removed:
            print('clayd is not installed as a service')
        return removed or cron_removed


def status():
    """Return install status string."""
    plat = _detect_platform()
    if plat == 'macos':
        return _status_launchd()
    elif plat == 'freebsd':
        return _status_cron()
    else:
        # Check systemd first, then cron fallback
        if os.path.exists(_SYSTEMD_UNIT) and shutil.which('systemctl'):
            return _status_systemd()
        return _status_cron()


def show_config():
    """Print what would be installed without installing."""
    plat = _detect_platform()
    print(f'Platform:  {plat}')
    _print_config()
    print(f'Log:       {_log_path()}')

    if plat == 'linux':
        ver = _systemd_version()
        distro = _detect_linux_distro()
        print(f'Distro:    {distro}')
        print(f'systemd:   {ver or "not found"}')
        if ver >= 240:
            print(f'Type:      exec (systemd 240+)')
        elif ver >= 230:
            print(f'Type:      simple (systemd <240)')
        else:
            print(f'Strategy:  cron @reboot fallback (systemd {ver or "N/A"})')

    print()
    if plat == 'macos':
        print(f'Target:    {_LAUNCHD_PLIST}')
        print(f'--- plist content ---')
        print(_launchd_plist_content())
    elif plat == 'linux' and _systemd_version() >= 230:
        print(f'Target:    {_SYSTEMD_UNIT}')
        print(f'--- unit content ---')
        print(_systemd_unit_content())
    else:
        print(f'Target:    crontab @reboot entry')
        print(f'--- cron entry ---')
        print(_cron_command())
