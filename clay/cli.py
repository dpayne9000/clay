import argparse
import json
import os
import sys
from . import __version__
from .run import engine
from .run.failure import WorkflowFailure
from .lib import config as app_config
from . import cloud as _auth
from . import sync as _sync

ACTION_TYPES = [
    "API", "scramda2", "humanDecision", "report", "mongo", "python", "transformData",
    "writeFile", "readFile",
    # agent actions
    "shell", "runCode", "loop", "humanShell",
    "writeSkill", "listSkills", "removeSkill", "searchSkills",
    "writeMemory", "searchMemory", "listMemory", "readMemory",
    "searchWeb", "browseWeb", "listSites", "loadSite",
    "createAgentAction",
    "deriveTags", "loadContext", "writeCode",
]


def _confirm_model_mismatch(problem):
    """Ask before a command uses a model outside its configured profiles."""
    print(f'clay: {problem}', file=sys.stderr)
    try:
        answer = input('Continue with the loaded model? [y/N] ')
    except (EOFError, KeyboardInterrupt):
        print('', file=sys.stderr)
        return False
    return answer.strip().lower() in {'y', 'yes'}


def _check_configuration(args, profiles):
    """Check only the models the pending command can use."""
    from .lib import config_check
    status = config_check.configuration_status(profiles)
    if status.model_mismatch and not getattr(args, 'events_socket', None):
        return _confirm_model_mismatch(status.problem)
    if status.problem:
        print(f'clay: {status.problem} — run `clay configure`.',
              file=sys.stderr)
    return True


def _pending_workflow(args, startup):
    """Resolve a pending file workflow without producing command output."""
    from .lib import paths

    command = getattr(args, 'command', None)
    if command == 'run' or (command == 'daemon'
                            and getattr(args, 'daemon_sub', None) == 'run'):
        explicit = getattr(args, 'file', None)
        segments = list(getattr(args, 'workflow_name', None) or [])
        if explicit and not segments:
            return paths.workflow_file(explicit)
        if segments and not explicit:
            return paths.find_workflow(*segments)
        return None
    if command is None:
        refs = startup.get('user') if isinstance(startup, dict) else None
        if refs and isinstance(refs[0], str):
            ref = refs[0].strip()
            return paths.workflow_file(ref) or paths.find_workflow(ref)
    return None

def _prompt_action():
    print(f"\n  Action types: {', '.join(ACTION_TYPES)}")
    action_type = input("  Action type: ").strip()
    if action_type not in ACTION_TYPES:
        print(f"  Unknown action type '{action_type}', skipping.")
        return None

    action = {"type": action_type}

    action_id = input("  Action id (optional, press enter to skip): ").strip()
    if action_id:
        action["id"] = action_id

    if action_type == "API":
        action["endpoint"] = input("  Endpoint URL: ").strip()

    elif action_type == "scramda2":
        action["prompt"] = input("  Prompt: ").strip()
        add_example = input("  Add a training example? (y/n): ").strip().lower() == "y"
        if add_example:
            question = input("  Example question: ").strip()
            answer = input("  Example answer: ").strip()
            action["examples"] = [{"question": question, "answer": answer}]
            action['max_tokens'] = 550

    elif action_type == "humanDecision":
        action["prompt"] = input("  Prompt text: ").strip()

    elif action_type == "report":
        action["template"] = input("  Template name: ").strip()

    elif action_type == "mongo":
        action["url"] = input("  Mongo URL: ").strip()
        action["db"] = input("  Database name: ").strip()
        action["collection"] = input("  Collection name: ").strip()

    elif action_type == "python":
        action["code"] = input("  Python code (single line): ").strip()

    elif action_type == "transformData":
        action["transform"] = input("  Transform expression: ").strip()

    included = input("  includedData keys (comma-separated, or enter to skip): ").strip()
    if included:
        action["includedData"] = [k.strip() for k in included.split(",") if k.strip()]

    return action

def create(args):
    output_file = args.workflow_name
    if not output_file.endswith(".json"):
        output_file += ".json"

    if os.path.exists(output_file):
        overwrite = input(f"File '{output_file}' already exists. Overwrite? (y/n): ").strip().lower()
        if overwrite != "y":
            print("Aborted.")
            return

    print(f"\nCreating workflow: {output_file}")

    # Collect steps
    steps_input = input("Enter step names (comma-separated): ").strip()
    steps = [s.strip() for s in steps_input.split(",") if s.strip()]

    action_sets = {}
    for step in steps:
        print(f"\n--- Actions for step '{step}' ---")
        action_sets[step] = []
        while True:
            add_action = input("  Add an action? (y/n): ").strip().lower()
            if add_action != "y":
                break
            action = _prompt_action()
            if action:
                action_sets[step].append(action)

    workflow = {
        "workflow": {"steps": steps},
        "actionSets": action_sets,
    }

    with open(output_file, "w") as f:
        json.dump(workflow, f, indent=4)

    print(f"\nWorkflow saved to '{output_file}'")

def configure_cmd(args):
    """Interactive wizard for provider, model, and generation settings.

    Writes straight to ~/.clay/config.json via app_config.write_user_config()
    — the one writer that module exposes. Ends by re-running the same
    advisory check `cli()` runs on every command, so leaving with no server
    running still says so, with the exact command to start one.
    """
    from .lib import config_check

    cfg = app_config.load_config()
    provider = dict(cfg.get('provider') or {})
    models = dict(cfg.get('models') or {})

    current_url = (provider.get('url') or 'http://127.0.0.1:8080').strip()
    url = input(f'Model server URL [{current_url}]: ').strip() or current_url

    current_default = (models.get('default') or 'unsloth/Qwen3-0.6B-GGUF:Q6_K').strip()
    default_model = input(
        f'Default model, as a Hugging Face repo:quant id [{current_default}]: '
    ).strip() or current_default
    models['default'] = default_model

    current_max_tokens = app_config.get_max_tokens()
    while True:
        entered = input(
            f'Default maximum response tokens [{current_max_tokens}]: '
        ).strip()
        if not entered:
            max_tokens = current_max_tokens
            break
        try:
            max_tokens = int(entered)
        except ValueError:
            max_tokens = 0
        if max_tokens > 0:
            break
        print('Maximum response tokens must be a positive whole number.')

    print("\nOther profiles clay looks for: code, chat, reports, orchestrator, "
          "telegram (or any name you choose) — selected in a workflow action "
          "with \"modelProfile\": \"<name>\".\n")
    while True:
        answer = input('Define or update another model profile? [y/N]: ').strip().lower()
        if answer not in ('y', 'yes'):
            break
        key = input('  Profile name: ').strip()
        if not key:
            print('  Skipped: no profile name given.')
            continue
        current = models.get(key, '')
        suffix = f' [{current}]' if current else ''
        value = input(f"  Model for '{key}'{suffix}: ").strip() or current
        if not value:
            print('  Skipped: no value given.')
            continue
        models[key] = value

    new_cfg = dict(cfg)
    new_cfg['provider'] = {**provider, 'url': url}
    new_cfg['models'] = models
    new_cfg['maxTokens'] = max_tokens
    app_config.write_user_config(new_cfg)
    print(f'\nSaved: {app_config._CONFIG_PATH}')

    problem = config_check.configuration_problem()
    if problem is None:
        print('Model server reachable and serving every configured model profile.')
    else:
        print(f'\n{problem}.\n')
        print(config_check.startup_instructions(url, default_model))


def _load_config():
    """Seed engine globals for a workflow run.

      __config__            configs/default.json, via lib.config
      __schema__            the cached ~/.clay/schema.json text. Run
                            `clay build` after changing an action's fields to
                            regenerate the cache; this does not recompute it.
      __workflow_template__ the workflows/registry/ skeleton tree as one JSON
                            document keyed by filename. Generated live, so it
                            is always current.

    Actions receive none of these unless they list them in includedData
    (clay/lib/context.py PASSTHROUGH_KEYS).
    """
    from .actions.skeleton import workflow_template_json
    return {
        '__config__': app_config.load_config(),
        '__schema__': app_config.load_schema(),
        '__workflow_template__': workflow_template_json(),
    }


def _resolve_startup_workflow(startup):
    """Resolve the single configured startup workflow, or report bad config."""
    from .lib import paths

    refs = startup.get('user') if isinstance(startup, dict) else None
    if (not isinstance(refs, list) or not refs
            or not isinstance(refs[0], str) or not refs[0].strip()):
        print('No startup workflow configured. startup.json must contain a '
              'non-empty string as the first item in "user".', file=sys.stderr)
        return None

    ref = refs[0].strip()
    target = paths.workflow_file(ref) or paths.find_workflow(ref)
    if target is None:
        print(f'No workflow matching "{ref}" (from startup.json). '
              f'Try:  clay workflows', file=sys.stderr)
    return target


def build(args):
    """Build developer artifacts, or interactively upgrade seeded workflows.

    ``clay build --upgrade`` compares only the template workflows that Clay
    initially seeds into the user directory. It is safe on an installed copy:
    accepted workflows are backed up and replaced as complete units, then the
    user-owned schema cache is rebuilt.

    Without ``--upgrade``, regenerate ~/.clay/schema.json and the registry tree
    from the action registry.

    The registry tree is generated *into the package*, at
    clay/data/workflows/system/registry — one copy, versioned with the code that
    produces it, so a schema change and its example tree land in the same commit.

    That makes this a checkout-only command. clay/data is read-only by contract
    on an installed clay: a wheel may sit somewhere the user cannot write, and
    its contents are replaced wholesale on upgrade, so anything written there
    would be silently discarded. Said out loud rather than failing on a
    permission error three lines later.
    """
    if getattr(args, 'upgrade', False):
        return _upgrade_seeded_workflows()

    from .actions.skeleton import WorkflowSkeleton

    dest = app_config.data_path('workflows', 'system', 'registry')
    writable = dest if os.path.isdir(dest) else app_config.data_path()
    if not os.access(writable, os.W_OK):
        print(f'clay build writes into the package itself:\n'
              f'    {dest}\n'
              f'which is not writable on an installed clay. It regenerates '
              f'committed source, so run it from a git checkout.',
              file=sys.stderr)
        return 1

    app_config.rebuild_schema()
    print(f'Rebuilt: {app_config._SCHEMA_PATH}')

    written = WorkflowSkeleton().write(dest)
    print(f'Rebuilt: {dest} ({len(written)} files)')


def _upgrade_seeded_workflows():
    """Offer complete shipped template workflows as interactive upgrades."""
    from .lib import workflow_upgrade

    source = app_config.data_path('workflows', 'templates')
    destination = app_config.user_path('workflows', 'templates')
    candidates = workflow_upgrade.upgrades(source, destination)
    backup = None
    upgraded = 0
    added = 0

    for candidate in candidates:
        if not candidate.exists:
            workflow_upgrade.install(candidate)
            print(f'Added workflow: {candidate.name}')
            added += 1
            continue
        if not candidate.changed:
            continue

        print(f'\nWorkflow changed: {candidate.name}\n')
        print(candidate.diff())
        answer = input('\nOverwrite this workflow with the shipped version? [y/N] ')
        if answer.strip().lower() not in ('y', 'yes'):
            print(f'Kept installed workflow: {candidate.name}')
            continue

        if backup is None:
            backup = workflow_upgrade.backup_root(app_config.clay_dir)
        saved = workflow_upgrade.install(candidate, backup)
        print(f'Upgraded workflow: {candidate.name}')
        print(f'Backup: {saved}')
        upgraded += 1

    app_config.rebuild_schema()
    print(f'Rebuilt: {app_config._SCHEMA_PATH}')
    print(f'Workflow upgrade complete: {added} added, {upgraded} upgraded.')


def dirs_cmd(args):
    """Inspect and edit the approved working directories.

    The one way to grant a directory without a run asking for it, which is what
    makes the unattended refusal actionable: a daemon run that refuses names
    this command, and a person runs it once from a terminal.
    """
    from pathlib import Path
    from .run import approval, workspaces

    sub = getattr(args, 'dirs_sub', None) or 'list'

    if sub == 'list':
        grants = workspaces.load()
        if not grants:
            print(f'No approved working directories. ({workspaces.REGISTER_PATH})')
            return
        for grant in grants:
            gates = ', '.join(f'{gate}={"ask" if grant.gates.get(gate) else "auto"}'
                              for gate in approval.GATES)
            print(f'{grant.path}\n    added {grant.added}    {gates}')
        return

    if sub == 'add':
        target = Path(args.path).expanduser().resolve()
        if not target.is_dir():
            print(f'Not a directory: {target}')
            return 1
        grant = workspaces.approve(target)
        print(f'Approved: {grant.path} (and everything under it)')
        return

    if sub == 'forget':
        target = Path(args.path).expanduser().resolve()
        if workspaces.forget(target):
            print(f'Removed: {target}')
            return
        print(f'Not in the register: {target}')
        return 1


def memory_cmd(args):
    """Manage persisted workflow memory by namespace."""
    from .actions.agent import memory_actions

    folder = memory_actions._namespace_dir(args.namespace)
    if not os.path.isdir(folder):
        print(f"No memories found in namespace '{args.namespace}'.")
        return

    removed = 0
    for name in os.listdir(folder):
        if name.endswith('.json') and not name.startswith('.'):
            os.unlink(os.path.join(folder, name))
            removed += 1
    print(f"Purged {removed} memories from '{args.namespace}'.")


def _start_event_socket(args):
    """If --events-socket was passed, connect the logger bridge."""
    from .run import logger as run_logger
    sock_path = getattr(args, 'events_socket', None)
    if sock_path:
        run_logger.start_socket_bridge(sock_path)


def _attach_terminal(args):
    """Attach the terminal renderer unless clayd is managing this process.

    A clayd-managed run (--events-socket) has no one watching its terminal, and
    the same events reach the real front-end over the socket bridge. Drawing
    them here as well is the duplicate-output trap.

    Which renderer is the only thing -v decides. Both draw the same event
    stream and neither can reach an event the workflow hid, so the flag
    changes how much of a run is drawn and never what a run does.

    Returns the renderer, or None. Callers must detach it in a finally block.
    """
    if getattr(args, 'events_socket', None):
        return None
    if getattr(args, 'verbose', False):
        from .run.renderers.terminal import TerminalRenderer as _Renderer
    else:
        from .run.renderers.concise import ConciseRenderer as _Renderer
    renderer = _Renderer()
    renderer.attach()
    return renderer


def _add_workflow_arg(parser, action_word):
    """Give a subcommand the two ways of naming a workflow.

    Every command that takes a workflow takes it the same way, so a reference
    that works for `run` works for `dryrun`, `lint` and `daemon run` without
    being retyped in another shape.
    """
    parser.add_argument('workflow_name', nargs='*', metavar='SEGMENT',
        help=f'Workflow to {action_word}, as path segments — '
             f'e.g. "templates research". Searched in your workflow folder, '
             f'then the ones clay ships with.')
    parser.add_argument('-f', '--file', metavar='PATH',
        help='An exact path to use instead, searched nowhere else. '
             'A directory means the main.json inside it.')


def _add_verbose_arg(parser):
    """Give a command that draws a run the switch between the two renderers.

    Defined once and added per subcommand rather than declared globally beside
    --plainStdout, so it reads where a person types it: `clay run -v system
    coding2`, not `clay -v run system coding2`. argparse only accepts a main
    parser's flags before the subcommand name.
    """
    parser.add_argument('-v', '--verbose', action='store_true',
        help='Draw the whole event stream — every action, the prompts sent to '
             'the model, skipped actions and INFO lines. Without it you get '
             'the answers, the files a turn changed and any warning.')


def _resolve_workflow_arg(args):
    """The workflow a command was pointed at, or None having said why not.

    Returns a path. Callers treat None as "stop, a message has been printed" —
    an unresolved name is a normal mistake (a typo, a workflow that lives
    somewhere else), not something worth a traceback.
    """
    from .lib import paths

    explicit = getattr(args, 'file', None)
    segments = list(getattr(args, 'workflow_name', None) or [])

    if explicit and segments:
        # Never guessed at. The two forms mean different things — one searches
        # and one does not — so picking a winner would silently ignore half of
        # what was typed.
        print(f'Say either -f {explicit} or the segments '
              f'"{" ".join(segments)}", not both.')
        return None

    if explicit:
        # Same rule as the segment form — the difference between the two is
        # where they look, not what counts as a workflow once found.
        hit = paths.workflow_file(explicit)
        if hit:
            return hit
        print(f'No workflow at {explicit}')
        return None

    if not segments:
        print('Say which workflow. Try:  clay workflows')
        return None

    hit = paths.find_workflow(*segments)
    if hit:
        return hit
    print(f'No workflow matching "{" ".join(segments)}". '
          f'Try:  clay workflows {segments[0]}')
    return None


def workflows_cmd(args):
    """List the workflows clay can find, by where they came from.

    Prints the segments to type rather than absolute paths, so a line can be
    copied straight back onto the command line. `--paths` when the real
    location is the question.
    """
    from .lib import paths

    term = (getattr(args, 'term', None) or '').strip().lower()
    found = paths.list_workflows()
    if term:
        found = [row for row in found if term in row[1].lower()]

    if not found:
        if term:
            print(f'No workflow matching "{term}".')
        else:
            print('No workflows found.')
        return 1

    # Shadowing is reported here and nowhere else: this is where someone is
    # looking for it, whereas a warning on every run would become noise.
    counts = {}
    for _label, ref, _path in found:
        counts[ref] = counts.get(ref, 0) + 1

    show_paths = getattr(args, 'paths', False)
    # The labels paths._folders emits, in its order. There is no 'cwd' heading
    # because the directory clay is run from is not searched — it is the
    # project directory, which is where a workflow works, not where one lives.
    headings = {'user': 'Yours', 'package': 'Shipped with clay'}
    for label in ('user', 'package'):
        rows = [row for row in found if row[0] == label]
        if not rows:
            continue
        print(f'\n{headings[label]}:')
        for _label, ref, path in rows:
            note = '  (also elsewhere)' if counts[ref] > 1 else ''
            print(f'  {ref}{note}')
            if show_paths:
                print(f'      {path}')
    print()
    return None


def _stored_workflow_reference(workflow):
    """Return a stable startup reference for a resolved workflow path."""
    workflow = os.path.abspath(workflow)
    for root in (app_config.clay_dir, app_config.data_path()):
        try:
            relative = os.path.relpath(workflow, root)
        except ValueError:
            continue
        if relative != os.pardir and not relative.startswith(os.pardir + os.sep):
            return relative
    return workflow


def default_cmd(args):
    """Show, set, or reset the workflow started by bare `clay`."""
    operation = getattr(args, 'default_operation', None)
    if operation is None:
        startup = app_config.load_startup()
        selected = startup.get('user') if isinstance(startup, dict) else None
        if not isinstance(selected, list) or not selected:
            print('No default workflow configured.')
            return 1
        print(selected[0])
        return None

    if operation == 'reset':
        try:
            with open(app_config._BASE_STARTUP_PATH, encoding='utf-8') as source:
                shipped = json.load(source)
            startup = app_config.load_startup()
            startup = dict(startup) if isinstance(startup, dict) else {}
            startup['user'] = list(shipped['user'])
            startup['_startupVersion'] = shipped.get('_startupVersion', 0)
            startup['_defaultManaged'] = True
            app_config.write_user_startup(startup)
        except (OSError, ValueError) as error:
            print(f'clay default: cannot load shipped default: {error}',
                  file=sys.stderr)
            return 1
        print(f'Default workflow reset to {startup["user"][0]}')
        return None

    workflow = _resolve_workflow_arg(args)
    if workflow is None:
        return 1
    startup = app_config.load_startup()
    startup = dict(startup) if isinstance(startup, dict) else {}
    reference = _stored_workflow_reference(workflow)
    startup['user'] = [reference]
    startup['_defaultManaged'] = False
    try:
        with open(app_config._BASE_STARTUP_PATH, encoding='utf-8') as source:
            shipped = json.load(source)
        startup['_startupVersion'] = shipped.get('_startupVersion', 0)
        app_config.write_user_startup(startup)
    except (OSError, ValueError) as error:
        print(f'clay default: could not save {app_config._STARTUP_PATH}: {error}',
              file=sys.stderr)
        return 1
    print(f'Default workflow set to {reference}')
    return None


def run(args):
    import os
    from .run import termui, logger as run_logger

    workflow = _resolve_workflow_arg(args)
    if workflow is None:
        return 1

    daemon = getattr(args, 'daemon', False)
    auto   = daemon or getattr(args, 'auto', False)
    if daemon and not _authorize_daemon_project_dir():
        return 1
    if auto and not daemon and not _authorize_project_dir():
        return 1

    if getattr(args, 'theme', None):
        os.environ['CLAY_THEME'] = args.theme
    termui.set_plain(getattr(args, 'plain_stdout', False))

    renderer = _attach_terminal(args)
    if renderer is not None:
        termui.intro()

    _start_event_socket(args)
    try:
        engine.run(workflow, auto=auto, daemon=daemon,
                   initial_data=_load_config())
    except WorkflowFailure:
        return 1
    finally:
        run_logger.stop_socket_bridge()
        if renderer is not None:
            renderer.detach()


def _authorize_project_dir() -> bool:
    """Authorize the project before the run becomes unattended."""
    from .lib import paths
    from .run import workspaces
    try:
        workspaces.authorize(paths.project_dir())
        return True
    except workspaces.WorkspaceDenied as exc:
        print(f'clay: {exc}', file=sys.stderr)
        return False


def _authorize_daemon_project_dir() -> bool:
    """Persist all unattended capabilities before a direct daemon run."""
    return _authorize_current_daemon_workspace(
        _terminal_daemon_permission_prompt)


def run_json(args):
    """Run workflow JSON from --file or stdin. Prompts use the event socket."""
    import sys
    file_path = getattr(args, 'file', None)
    if file_path:
        with open(file_path) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)
    from .lib import config_check
    if not _check_configuration(args, config_check.model_profiles_in_data(data)):
        return 1
    from .run import logger as run_logger
    label = data.get('name', 'api-run')
    auto = not getattr(args, 'no_auto', False)
    _start_event_socket(args)
    try:
        engine.run_from_data(data, label=label, auto=auto,
                             initial_data=_load_config())
    except WorkflowFailure:
        return 1
    finally:
        run_logger.stop_socket_bridge()

def ui(args):
    """Launch the PySide6/Qt desktop UI, whose runs execute through clayd."""
    import sys
    try:
        from PySide6.QtWidgets import QApplication
        from .ui.window import WorkflowWindow
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith('PySide6'):
            print(
                "This Clay installation does not contain the Qt desktop UI. "
                "Install the UI release; source developers can install it "
                "with: python -m pip install -e '.[ui]'",
                file=sys.stderr,
            )
            return 1
        raise
    from .lib import paths

    app = QApplication(sys.argv[:1])
    app.setApplicationName('clay')
    app.setOrganizationName('clay')
    from .ui.preflight import ensure_daemon_with_qt
    if not ensure_daemon_with_qt():
        return 1
    win = WorkflowWindow()
    win.show()
    # Open each workflow argument in its own tab.
    for ref in getattr(args, 'workflows', []) or []:
        path = paths.workflow_file(ref) or paths.find_workflow(ref)
        if path:
            win.load_workflow(path)
        else:
            print(f'No workflow at {ref} — skipped.')
    sys.exit(app.exec())


def _terminal_daemon_permission_prompt(check) -> bool:
    """Ask visibly before persisting unattended access for this directory."""
    from .run import approval, workspaces
    labels = {
        'fileReads': 'read files',
        'fileWrites': 'write files',
        'commands': 'run commands',
    }
    missing = ', '.join(labels[gate] for gate in approval.GATES
                        if gate in check.missing)
    text = (
        'CLAY needs advance permission for an unattended daemon workflow.\n\n'
        f'Directory: {check.path}\n'
        f'Missing:   {missing}\n\n'
        f'Grant these permissions for {check.path} in '
        f'{workspaces.REGISTER_PATH}? [y/N] '
    )
    try:
        answer = input(text)
    except EOFError:
        return False
    return str(answer or '').strip().lower() in ('y', 'yes')


def _ensure_daemon(confirm=None):
    """Authorize the current project, then start clayd if needed."""
    from .daemon.client import ensure_daemon
    if not _authorize_current_daemon_workspace(
            confirm or _terminal_daemon_permission_prompt):
        return False
    return ensure_daemon()


def _authorize_current_daemon_workspace(confirm) -> bool:
    """Translate daemon permission refusal into the CLI's status contract."""
    from .daemon.client import authorize_daemon_workspace, DaemonPermissionDenied
    from .lib import paths
    try:
        authorize_daemon_workspace(paths.project_dir(), confirm)
    except DaemonPermissionDenied as exc:
        print(f'clay: {exc}', file=sys.stderr)
        return False
    return True


# ── Daemon CLI commands ──────────────────────────────────────────────────────

def daemon_cmd(args):
    """Handle `clay daemon <subcommand>`."""
    sub = args.daemon_sub

    if sub == 'start':
        if not _ensure_daemon():
            return 1
        print('clayd is running')

    elif sub == 'stop':
        from .daemon.client import DaemonClient
        try:
            with DaemonClient() as c:
                c.shutdown()
            print('clayd: shutdown requested')
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            print('clayd is not running')

    elif sub == 'status':
        from .daemon.client import DaemonClient
        try:
            with DaemonClient() as c:
                resp = c.ping()
            pid_file = os.path.expanduser('~/.clay/clayd.pid')
            pid = open(pid_file).read().strip() if os.path.exists(pid_file) else '?'
            print(f'clayd: running (pid {pid})')
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            print('clayd: not running')
        from .daemon.install import status as _svc_status
        print(f'service:  {_svc_status()}')

    elif sub == 'list':
        from .daemon.client import DaemonClient
        try:
            with DaemonClient() as c:
                workflows = c.list_workflows()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            print('clayd is not running')
            return
        if not workflows:
            print('No workflows running')
            return
        fmt = '{:<10} {:<20} {:<10} {:>8} {:>6} {:>6}'
        print(fmt.format('ID', 'NAME', 'STATUS', 'RUNTIME', 'ITERS', 'EVTS'))
        print('-' * 68)
        for wf in workflows:
            rt = wf.get('runtime', 0)
            m, s = divmod(rt, 60)
            h, m = divmod(m, 60)
            rt_str = f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'
            print(fmt.format(
                wf['id'], wf['name'][:20], wf['status'],
                rt_str, wf.get('iterations', 0), wf.get('events_received', 0),
            ))

    elif sub == 'run':
        from .daemon.client import DaemonClient, DaemonPermissionDenied
        from .run import workspaces
        # Resolved here, before it goes over the wire: clayd resolves nothing,
        # and it does not share this process's working directory, so a
        # relative reference would mean something different on the far side.
        workflow = _resolve_workflow_arg(args)
        if workflow is None:
            return 1
        if not _ensure_daemon():
            return 1
        try:
            with DaemonClient() as c:
                resp = c.start_workflow(
                    workflow,
                    auto=getattr(args, 'auto', False),
                    daemon_mode=getattr(args, 'daemon_mode', False),
                )
            if resp.get('ok'):
                print(f'Started {resp["id"]} (pid {resp.get("pid", "?")})')
            else:
                print(f'Error: {resp.get("error", "unknown")}', file=sys.stderr)
        except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
            print(f'Cannot connect to clayd: {e}', file=sys.stderr)
        except workspaces.WorkspaceDenied as e:
            print(f'clay: {e}', file=sys.stderr)
            return 1
        except DaemonPermissionDenied as e:
            print(f'clay: {e}', file=sys.stderr)
            return 1

    elif sub == 'kill':
        from .daemon.client import DaemonClient
        try:
            with DaemonClient() as c:
                resp = c.stop_workflow(args.wf_id)
            if resp.get('ok'):
                print(f'Stopped {args.wf_id}')
            else:
                print(f'Error: {resp.get("error", "unknown")}')
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            print('clayd is not running')

    elif sub == 'tail':
        from .daemon.client import DaemonClient
        try:
            with DaemonClient() as c:
                lines = c.tail(args.wf_id, lines=getattr(args, 'lines', 50))
            for line in lines:
                print(line)
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            print('clayd is not running')

    elif sub == 'install':
        from .daemon.install import install, show_config
        if getattr(args, 'dry_run', False):
            show_config()
        else:
            install()

    elif sub == 'uninstall':
        from .daemon.install import uninstall
        uninstall()

    elif sub == 'attach':
        from .daemon.client import DaemonClient
        from .run.renderers.detail import payload_lines, skipped_reason
        if not _ensure_daemon():
            return 1
        try:
            client = DaemonClient()
            client.connect()
            print(f'Attached to {args.wf_id} (Ctrl+C to detach, type to send input)')
            for event in client.subscribe(args.wf_id):
                ev = event.get('event', '')
                if ev == 'stdout':
                    print(event.get('line', ''))
                elif ev == 'stderr':
                    print(f'[stderr] {event.get("line", "")}')
                elif ev == 'prompt':
                    text = event.get('text', '')
                    try:
                        resp = input(f'{text}> ')
                        client._send({'cmd': 'input', 'id': args.wf_id, 'text': resp})
                    except EOFError:
                        break
                elif ev == 'finished':
                    print(f'\nProcess exited ({event.get("exit_code", "?")})')
                    break
                elif ev == 'workflow':
                    data = event.get('data', {})
                    t = data.get('type', '')
                    if t == 'step.start':
                        print(f'\n── {data.get("step", "")} ──')
                    elif t == 'action.start':
                        print(f'  ▸ {data.get("action_type", "")}  →  {data.get("id", "")}')
                    elif t == 'action.complete' and data.get('action_type') == 'scramda2':
                        print(data.get('data') or '')
                    elif t in ('action.error', 'run.error'):
                        print(f'  !! {data.get("message", "")}')
                    elif t == 'action.output':
                        # File contents, command output and model prompts used
                        # to arrive as log events and were drawn below.
                        print(payload_lines(data))
                    elif t == 'action.skipped':
                        print(f'  skipped {data.get("id", "")} '
                              f'({skipped_reason(data)})')
                    elif t == 'log':
                        print(f'  {data.get("message", "")}')
        except KeyboardInterrupt:
            print('\nDetached')
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            print('clayd is not running')


def dryrun(args):
    # load_file emits run.error instead of printing; without a renderer a
    # missing workflow file would fail with no message at all.
    workflow = _resolve_workflow_arg(args)
    if workflow is None:
        return 1

    renderer = _attach_terminal(args)
    try:
        engine.dry_run(workflow)
        print(f"Performing a dry run for workflow: {workflow}")
    finally:
        if renderer is not None:
            renderer.detach()

def docs(args):
    """Generate action reference HTML and JSON to docs/documentation/."""
    import importlib.util
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gen_path = os.path.join(here, 'docs', 'generate_action_reference.py')
    spec = importlib.util.spec_from_file_location('generate_action_reference', gen_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from .actions.registry import all_schemas
    schema = all_schemas()
    count = len(schema.get('oneOf', []))

    out_dir = os.path.join(here, 'docs', 'documentation')
    os.makedirs(out_dir, exist_ok=True)

    json_path = os.path.join(out_dir, 'action-reference.json')
    with open(json_path, 'w') as f:
        json.dump(json.loads(json.dumps(schema)), f, indent=2)
    print(f'Generated: {os.path.relpath(json_path)}')

    html_path = os.path.join(out_dir, 'action-reference.html')
    with open(html_path, 'w') as f:
        f.write(mod.generate_html(schema))
    print(f'Generated: {os.path.relpath(html_path)}')
    print(f'  {count} action types included')


def lint(args):
    from .lint import lint as _lint, report
    from .lib import paths

    segments = list(getattr(args, 'path', None) or [])

    if not segments:
        # No argument means "lint my workflows" — the writable folder, the one
        # holding the workflows a person edits. Not the packaged folder behind
        # it, which is the program's own and not something a user can fix, and
        # not the project directory, which holds work rather than workflows.
        target = paths.workflow_folder()
        if not os.path.isdir(target):
            print(f"lint: {target} does not exist — name a workflow to lint",
                  file=sys.stderr)
            return 1
        return report(_lint(target))

    # find_tree, not find_workflow: linting a directory means every file under
    # it. An exact path on disk wins, so `clay lint ./scratch` still lints
    # ./scratch even if a workflow of that name is installed.
    given = os.path.join(*segments)
    target = given if os.path.exists(given) else paths.find_tree(*segments)
    if target is None:
        print(f"lint: path not found: {given}", file=sys.stderr)
        return 1
    return report(_lint(target))


def check_context_cmd(args):
    """Report resolved scramda2 prompt sizes without running the workflow."""
    from .context_check import inspect_workflow, report

    workflow = _resolve_workflow_arg(args)
    if workflow is None:
        return 1

    context = {}
    context_file = getattr(args, 'context_file', None)
    if context_file:
        try:
            with open(context_file, encoding='utf-8') as source:
                context = json.load(source)
            if not isinstance(context, dict):
                raise ValueError('top-level value must be a JSON object')
        except (OSError, ValueError) as exc:
            print(f'check context: cannot load {context_file}: {exc}', file=sys.stderr)
            return 1

    return report(inspect_workflow(workflow, context), workflow)


# ── Auth & sync commands ─────────────────────────────────────────────────────

def login_cmd(args):
    try:
        user = _auth.login(
            username=getattr(args, 'username', None),
            password=getattr(args, 'password', None),
            server=getattr(args, 'server', None),
        )
        print(f'Logged in as {user}')
    except _auth.AuthError as e:
        print(f'Login failed: {e}', file=sys.stderr)
        sys.exit(1)


def logout_cmd(_args):
    _auth.logout()
    print('Logged out')


def whoami_cmd(_args):
    user = _auth.current_user()
    if user:
        print(f'Logged in as {user} ({_auth.api_url()})')
    else:
        print('Not logged in')


def push_cmd(args):
    from .lib import paths as _paths
    paths = args.paths or [_paths.workflow_folder()]
    try:
        _sync.push(paths, verbose=args.verbose)
    except _auth.AuthError as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)


def pull_cmd(args):
    from .lib import paths as _paths
    dest = args.dir or _paths.workflow_folder()
    try:
        _sync.pull(dest, verbose=args.verbose)
    except _auth.AuthError as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)

def cli():
    parser = argparse.ArgumentParser(description="A tool with multiple command subsets.")
    parser.add_argument("--version", action="version", version=f"clay {__version__}")
    # Global flags — can be placed anywhere: python clay.py --ci run foo.json
    parser.add_argument("--daemon", action="store_true",
        help="Fully unattended: AI answers decisions, shell commands auto-approved")
    parser.add_argument("--plainStdout", "--ci", dest="plain_stdout",
        action="store_true", help="Disable ANSI colours and animations (CI-safe)")
    parser.add_argument("--theme", metavar="PATH",
        help="Path to a .theme file (or set CLAY_THEME env var)")
    parser.add_argument("--project-dir", metavar="PATH", dest="project_dir",
        help="The directory this run works in — where file actions read and "
             "write. Defaults to the current directory. clayd passes it "
             "explicitly, because a workflow it spawns does not inherit the "
             "cwd of whoever asked for it.")
    subparsers = parser.add_subparsers(dest="command", required=False, help="Subcommands")

    # Create parser
    parser_create = subparsers.add_parser("create", help="Create a new resource")
    parser_create.add_argument("workflow_name", help="Name of the workflow to create")
    parser_create.set_defaults(func=create)

    # Run parser
    parser_run = subparsers.add_parser("run", help="Run the process")
    _add_workflow_arg(parser_run, "run")
    parser_run.add_argument("--auto", action="store_true", help="Replace humanDecision steps with AI-generated answers")
    parser_run.add_argument("--events-socket", metavar="PATH",
        help="Unix socket path for JSON-line event stream (used by UI)")
    _add_verbose_arg(parser_run)
    parser_run.set_defaults(func=run)

    # Dryrun parser
    parser_dryrun = subparsers.add_parser("dryrun", help="Perform a dry run of the process")
    _add_workflow_arg(parser_dryrun, "dry-run")
    _add_verbose_arg(parser_dryrun)
    parser_dryrun.set_defaults(func=dryrun)

    # Workflows parser — what the segment form above can actually find
    parser_workflows = subparsers.add_parser(
        "workflows", help="List the workflows clay can find")
    parser_workflows.add_argument("term", nargs="?",
        help="Show only workflows whose reference contains this text")
    parser_workflows.add_argument("--paths", action="store_true",
        help="Also show the file each one resolves to")
    parser_workflows.set_defaults(func=workflows_cmd)

    parser_default = subparsers.add_parser(
        "default", help="Show or select the workflow bare `clay` starts")
    default_subs = parser_default.add_subparsers(dest="default_operation")
    default_set = default_subs.add_parser("set", help="Select a default workflow")
    _add_workflow_arg(default_set, "set as the default")
    default_set.set_defaults(func=default_cmd)
    default_reset = default_subs.add_parser(
        "reset", help="Follow Clay's shipped default again")
    default_reset.set_defaults(func=default_cmd)
    parser_default.set_defaults(func=default_cmd)

    # Run-json parser — reads full workflow JSON, used by the API
    parser_run_json = subparsers.add_parser(
        "run-json",
        help="Run a workflow from a JSON payload (API-triggered, never reads workflow files)"
    )
    parser_run_json.add_argument(
        "--file",
        metavar="PATH",
        help="Read workflow JSON from PATH instead of stdin (frees stdin for interactive input)"
    )
    parser_run_json.add_argument(
        "--no-auto",
        dest="no_auto",
        action="store_true",
        help="Disable auto mode; humanDecision prompts are exchanged via JSON markers on stdout/stdin"
    )
    parser_run_json.add_argument("--events-socket", metavar="PATH",
        help="Unix socket path for JSON-line event stream (used by UI)")
    parser_run_json.set_defaults(func=run_json)

    # Docs parser
    parser_docs = subparsers.add_parser("docs", help="Generate action reference HTML documentation")
    parser_docs.set_defaults(func=docs)

    # UI parser
    parser_ui = subparsers.add_parser(
        "ui", help="Launch the PySide6/Qt desktop UI (runs through clayd)")
    parser_ui.add_argument("workflows", nargs="*", help="Workflow files to open on launch")
    parser_ui.set_defaults(func=ui)

    # Daemon parser — manage the system daemon
    parser_daemon = subparsers.add_parser("daemon", help="Manage the clayd process daemon")
    daemon_subs = parser_daemon.add_subparsers(dest="daemon_sub", help="Daemon subcommands")

    daemon_subs.add_parser("start", help="Start the daemon (if not running)")
    daemon_subs.add_parser("stop", help="Stop the daemon")
    daemon_subs.add_parser("status", help="Check if daemon is running")
    daemon_subs.add_parser("list", help="List managed workflows")

    ds_run = daemon_subs.add_parser("run", help="Start a workflow via the daemon")
    _add_workflow_arg(ds_run, "run")
    ds_run.add_argument("--auto", action="store_true")
    ds_run.add_argument("--daemon-mode", action="store_true",
        help="Fully unattended (auto + no prompts)")
    # Repeated here so `clay daemon run -h` shows it: this is the one command
    # where the directory is a real question, because the workflow runs under
    # clayd rather than in this shell. SUPPRESS so that omitting it leaves
    # whatever the global flag parsed — an argparse subparser default would
    # otherwise overwrite `clay --project-dir X daemon run ...` with None.
    ds_run.add_argument("--project-dir", metavar="PATH", dest="project_dir",
        default=argparse.SUPPRESS,
        help="Directory the workflow works in — where its file actions read "
             "and write. Defaults to the directory you run this from.")

    ds_kill = daemon_subs.add_parser("kill", help="Stop a running workflow")
    ds_kill.add_argument("wf_id", help="Workflow ID (e.g. wf-0001)")

    ds_tail = daemon_subs.add_parser("tail", help="Show recent output of a workflow")
    ds_tail.add_argument("wf_id", help="Workflow ID")
    ds_tail.add_argument("-n", "--lines", type=int, default=50, help="Number of lines")

    ds_attach = daemon_subs.add_parser("attach", help="Attach to a workflow's stdout/stdin")
    ds_attach.add_argument("wf_id", help="Workflow ID")

    ds_install = daemon_subs.add_parser("install",
        help="Register clayd as a system service (launchd/systemd)")
    ds_install.add_argument("--dry-run", action="store_true",
        help="Show what would be installed without installing")

    daemon_subs.add_parser("uninstall",
        help="Remove clayd system service registration")

    parser_daemon.set_defaults(func=daemon_cmd)

    # Dirs parser — the approved working directories register
    parser_dirs = subparsers.add_parser(
        "dirs", help="Manage the directories clay's file actions may use")
    dirs_subs = parser_dirs.add_subparsers(dest="dirs_sub", help="Directory subcommands")
    dirs_subs.add_parser("list", help="Show every approved directory and its gates")
    dirs_add = dirs_subs.add_parser(
        "add", help="Approve a directory and everything under it")
    dirs_add.add_argument("path", help="Directory to approve")
    dirs_forget = dirs_subs.add_parser(
        "forget", help="Remove one directory from the register")
    dirs_forget.add_argument("path", help="Directory to remove")
    parser_dirs.set_defaults(func=dirs_cmd)

    # Memory parser — explicit namespace purge for accumulated workflow state
    parser_memory = subparsers.add_parser(
        "memory", help="Manage persisted workflow memory")
    memory_subs = parser_memory.add_subparsers(
        dest="memory_action", required=True, help="Memory subcommands")
    memory_purge = memory_subs.add_parser(
        "purge", help="Delete every memory entry in one namespace")
    memory_purge.add_argument("namespace", help="Namespace to empty")
    parser_memory.set_defaults(func=memory_cmd)

    # Build parser — regenerate ~/.clay/schema.json from the action registry
    parser_build = subparsers.add_parser(
        "build", help="Build registry artifacts or upgrade seeded workflows")
    parser_build.add_argument(
        "--upgrade", action="store_true",
        help="Offer upgrades for the template workflows seeded at install")
    parser_build.set_defaults(func=build)

    # Configure parser — provider, models, and token limit in config.json.
    parser_configure = subparsers.add_parser(
        "configure", aliases=["config"],
        help="Set model server, profiles, and token limit in ~/.clay/config.json")
    parser_configure.set_defaults(func=configure_cmd)

    # Lint parser
    parser_lint = subparsers.add_parser("lint", help="Validate workflow and data JSON files")
    parser_lint.add_argument(
        "path",
        nargs="*",
        metavar="SEGMENT",
        help="File, directory, or workflow segments to lint (default: your workflow folder)",
    )
    parser_lint.set_defaults(func=lint)

    # Check parser — read-only workflow diagnostics.
    parser_check = subparsers.add_parser(
        "check", help="Inspect workflow runtime inputs without running it")
    check_subs = parser_check.add_subparsers(dest="check_operation", required=True)
    parser_check_context = check_subs.add_parser(
        "context", help="Show resolved scramda2 prompt character counts")
    _add_workflow_arg(parser_check_context, "check")
    parser_check_context.add_argument(
        "--context", dest="context_file", metavar="FILE",
        help="JSON object containing representative runtime values")
    parser_check_context.set_defaults(func=check_context_cmd)

    # ── Auth & sync subcommands ──────────────────────────────────────────────

    # Cloud commands are intentionally unavailable 
    #
    # parser_login = subparsers.add_parser("login", help="Log in to the clay cloud API")
    # parser_login.add_argument("--username", "-u", help="Username (prompted if omitted)")
    # parser_login.add_argument("--password", "-p", help="Password (prompted if omitted)")
    # parser_login.add_argument("--server", "-s", help="API URL (default: http://localhost:3000)")
    # parser_login.set_defaults(func=login_cmd)
    #
    # parser_logout = subparsers.add_parser("logout", help="Log out and remove stored credentials")
    # parser_logout.set_defaults(func=logout_cmd)
    #
    # parser_whoami = subparsers.add_parser("whoami", help="Show the currently logged-in user")
    # parser_whoami.set_defaults(func=whoami_cmd)
    #
    # parser_push = subparsers.add_parser("push", help="Push local workflows to the cloud")
    # parser_push.add_argument("paths", nargs="*", help="Files or directories to push (default: your workflow folder)")
    # parser_push.add_argument("--verbose", "-v", action="store_true")
    # parser_push.set_defaults(func=push_cmd)
    #
    # parser_pull = subparsers.add_parser("pull", help="Pull workflows from the cloud to local directory")
    # parser_pull.add_argument("--dir", "-d", help="Destination directory (default: your workflow folder)")
    # parser_pull.add_argument("--verbose", "-v", action="store_true")
    # parser_pull.set_defaults(func=pull_cmd)

    args = parser.parse_args()

    # The directory clay works in, fixed once. Every action that reaches the
    # filesystem resolves against this rather than reading cwd again later, so
    # a workflow cannot be moved out from under itself by a chdir mid-run, and
    # a run started here means the same directory wherever it ends up
    # executing — including inside clayd, whose own cwd is clay's checkout.
    #
    # --project-dir wins over cwd because a workflow spawned by clayd has no
    # useful cwd of its own: the daemon is a long-lived process started from
    # somewhere unrelated, so the directory the *asking* client stood in has to
    # travel over the wire and arrive here as a flag.
    from .lib import paths as _paths
    project_dir = args.project_dir or os.getcwd()
    if not os.path.isdir(project_dir):
        print(f'--project-dir: not a directory: {project_dir}', file=sys.stderr)
        return 1
    _paths.set_project_dir(project_dir)

    # Seeding happens here and nowhere else: importing a module must not touch
    # the filesystem, and doing it after parse_args means `clay --help` and a
    # mistyped command exit without creating anything. What it copies is
    # reported rather than done quietly — files appearing in a home directory
    # unannounced is exactly the kind of thing that is hard to trace later.
    skip_seed = ()
    if getattr(args, 'func', None) is build and getattr(args, 'upgrade', False):
        # The upgrade path owns template installation as complete workflow
        # units. It must compare before any ordinary copy-missing seed changes
        # the destination, and it should not mutate unrelated seeded content.
        skip_seed = app_config.SEEDED_DIRS
    seeded = app_config.seed_user_dir(skip=skip_seed)
    if seeded:
        print(f'clay: prepared {app_config.clay_dir} ({len(seeded)} files)')

    startup = app_config.load_startup()

    # Connection and configuration problems remain advisory. A confirmed
    # model-identity mismatch is different: stop before doing work unless the
    # user explicitly accepts the loaded model. An event-socket child inherits
    # the choice already made by the client that launched it and cannot prompt.
    command = getattr(args, 'command', None)
    if command not in {'configure', 'run-json', 'check'}:
        from .lib import config_check
        pending = _pending_workflow(args, startup)
        profiles = (config_check.model_profiles_in_workflow(pending)
                    if pending else set())
        if not _check_configuration(args, profiles):
            return 1

    # Returned, not discarded: this function is the console-script entry point
    # (`clay = "clay.cli:cli"`), so what it returns becomes the process exit
    # code. A command that reports a failure has to be able to make the shell
    # see one — `clay run nonexistent && deploy` must not reach deploy.
    if hasattr(args, 'func'):
        return args.func(args)
    else:
        # No subcommand: the startup workflow. Resolved here rather than handed
        # to engine.run as typed — startup.json names a workflow the same way a
        # person does, and engine.run takes a resolved file.
        target = _resolve_startup_workflow(startup)
        if target is None:
            return 1
        try:
            engine.run(target)
        except WorkflowFailure as exc:
            print(str(exc), file=sys.stderr)
            return 1

# if __name__ == "__main__":
#     main()
