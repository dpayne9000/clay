"""Telegram control channel for clay workflows.

The bot is a front-end for clayd, exactly like the Qt UI: it never runs a
workflow itself. Menu presses ask clayd to start a workflow, prompts raised by
that workflow arrive as clayd events and are relayed to the chat, and chat
replies are handed back to clayd as input.

Nothing in this module touches the network or the environment at import time —
clay.actions.registry.discover() imports every action module on every command,
so a missing TELEGRAM_BOT_TOKEN must not be able to break unrelated runs. The
token is read, and the bot built, only when the action actually executes.

Workflow menu entries come from the action itself:

    {
      "type": "telegram",
      "id": "bot",
      "workflows": [
        {"label": "System editor", "path": "workflows/system/editor/main.json"}
      ]
    }
"""

import os
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from ...adapters import gopher
from ...channels.message_batcher import MessageBatcher
from ...channels.telegram_bridge import TelegramBridge, inline_menu
from ...daemon.client import DaemonClient, EventSubscriber, ensure_daemon
from ...lib import config as app_config
from ...run import approval, events as run_events, logger
from ...run.renderers.chat import ConciseChatRenderer
from ..registry import action as _action_decorator, req, opt, handler_for


@_action_decorator('telegram', skeleton=False)
class Telegram:
    id: str = req(
        "telegram is an action that persists, and hosts a telegram bot channel. "
        "It requires TELEGRAM_BOT_TOKEN plus a non-empty "
        "TELEGRAM_ALLOWED_USERS or TELEGRAM_ALLOWED_CHATS environment "
        "allowlist, and runs until manually stopped")
    workflows: list = opt(
        "Menu entries shown in the bot's control panel: "
        '[{"label": "...", "path": "workflows/.../main.json"}]',
        None)


# Telegram caps callback_data at 64 bytes, so buttons carry an index into the
# configured entries rather than a workflow path.
_CALLBACK_PREFIX = 'wf:'

DAEMON_ERRORS = (ConnectionError, ConnectionRefusedError, FileNotFoundError, OSError)
_ALLOWED_USERS_ENV = 'TELEGRAM_ALLOWED_USERS'
_ALLOWED_CHATS_ENV = 'TELEGRAM_ALLOWED_CHATS'


def _telegram_ids(environment, name: str) -> set[int]:
    """Parse one comma/whitespace-separated Telegram ID allowlist."""
    raw = str(environment.get(name) or '').replace(',', ' ')
    ids = set()
    for token in raw.split():
        try:
            value = int(token)
        except ValueError as exc:
            raise ValueError(
                f'{name} contains a non-numeric Telegram ID: {token!r}'
            ) from exc
        if value == 0:
            raise ValueError(f'{name} contains invalid Telegram ID 0')
        ids.add(value)
    return ids


def telegram_allowlists(environment=None) -> tuple[set[int], set[int]]:
    """Return required user/chat allowlists, failing closed when absent."""
    environment = os.environ if environment is None else environment
    users = _telegram_ids(environment, _ALLOWED_USERS_ENV)
    chats = _telegram_ids(environment, _ALLOWED_CHATS_ENV)
    if not users and not chats:
        raise ValueError(
            'telegram requires a non-empty TELEGRAM_ALLOWED_USERS or '
            'TELEGRAM_ALLOWED_CHATS allowlist'
        )
    return users, chats


@dataclass(frozen=True)
class MenuEntry:
    """One workflow offered in the bot's control panel."""

    label: str
    path: str


@dataclass
class ActiveRun:
    """The single workflow this bot currently has running under clayd."""

    wf_id: str
    label: str
    chat_id: int
    prompt_id: str = ''
    awaiting_input: bool = False
    # Whether this run has been told the chat's approval settings yet. They are
    # pushed on the first event rather than at launch: set_option needs the
    # workflow's event socket, and at launch clayd has only just spawned the
    # process. The first event is proof the socket is up.
    approval_pushed: bool = False
    # Every line relayed during the run. clayd's stdout capture is empty now
    # that the engine only emits, so the closing summary is built from what
    # actually arrived.
    output: list = field(default_factory=list)


class Typing:
    """Keeps Telegram's "typing…" hint up for as long as a wait lasts.

    Telegram clears the hint after about five seconds, so a single call cannot
    cover a model call that runs for a minute — which is the case worth showing
    at all. One daemon thread re-sends it on an interval instead.

    Stopping joins the thread, so start/stop pairs cannot accumulate threads
    over a long-lived bot. MAX_SECONDS is the guard for the pair that never
    completes: a workflow whose socket drops mid-call never sends its
    active=False, and a keepalive with no ceiling would type into that chat
    until the bot was restarted.
    """

    INTERVAL = 4.0
    MAX_SECONDS = 600.0

    def __init__(self, send, *, interval: float = INTERVAL,
                 max_seconds: float = MAX_SECONDS) -> None:
        self._send = send
        self._interval = interval
        self._max_seconds = max_seconds
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self, chat_id) -> None:
        """Begin typing in `chat_id`. Restarts if already typing elsewhere."""
        self.stop()
        with self._lock:
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(chat_id, self._stop),
                name='telegram-typing', daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Idempotent. Returns once the thread has actually finished."""
        with self._lock:
            thread, stop = self._thread, self._stop
            self._thread = None
        stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._interval + 1.0)

    def _run(self, chat_id, stop: threading.Event) -> None:
        deadline = time.monotonic() + self._max_seconds
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                self._send(chat_id)
            except Exception as error:
                # One failed hint is not worth losing the run over, and it is
                # not worth a message in the chat either — the user is already
                # looking at a thread that is about to receive the real reply.
                logger.debug(f'telegram: typing hint failed: {error}')
                return
            stop.wait(self._interval)


def menu_entries(configured) -> list[MenuEntry]:
    """Build menu entries from the action's `workflows` param.

    Malformed entries raise rather than being skipped — a button silently
    missing from the panel is worse than a startup error naming the problem.
    """
    entries: list[MenuEntry] = []
    for index, item in enumerate(configured or []):
        if not isinstance(item, dict):
            raise ValueError(
                f'telegram workflows[{index}] must be an object with '
                '"label" and "path"')
        label = (item.get('label') or '').strip()
        path = (item.get('path') or '').strip()
        if not label or not path:
            raise ValueError(
                f'telegram workflows[{index}] needs both "label" and "path"')
        entries.append(MenuEntry(label=label, path=path))
    return entries


class TelegramWorkflowBot:
    """Relays between a Telegram chat and clayd.

    The bridge, the daemon client and the renderer are injected so the wiring
    can be tested without a network or a running daemon.

    The chat sees the same content as a CLI run without -v:
    ConciseChatRenderer decides that from the same events ConciseRenderer
    consumes. This class only decides where the text goes and when — batching
    output so a turn is a few messages rather than a notification per event.
    """

    def __init__(
        self,
        bridge,
        entries,
        *,
        client_factory=DaemonClient,
        subscriber_factory=EventSubscriber,
        renderer=None,
        batch_interval: float = 1.5,
        typing_hint=None,
    ) -> None:
        self._bridge = bridge
        self._entries = list(entries)
        self._client_factory = client_factory
        self._subscriber_factory = subscriber_factory
        self._renderer = renderer or ConciseChatRenderer()

        self._lock = threading.Lock()
        self._active: Optional[ActiveRun] = None
        # This chat's approval choices, pushed into every workflow it starts.
        # Empty means nobody has said anything, and a run keeps whatever
        # ~/.clay/config.json gives it — an unset chat must not override a
        # deliberate config setting with a default of its own.
        self._approval: dict = {}
        self._subscriber = None
        self._stopped = threading.Event()
        self._batcher = MessageBatcher(self._send_batch,
                                       interval=batch_interval)
        # The chat's answer to "is it still working?". A busy event draws no
        # text — ConciseChatRenderer returns None for it — because a
        # "working…" line
        # per action would be the noisiest thing in the thread and would still
        # be there after the wait ended.
        self._typing = typing_hint or Typing(self._type_hint)

        self._register()

    # ── wiring ───────────────────────────────────────────────────────────

    def _register(self) -> None:
        bridge = self._bridge
        bridge.command('start', description='Open the control panel')(self._cmd_start)
        bridge.command('status', description='Show the running workflow')(self._cmd_status)
        bridge.command('cancel', description='Stop the running workflow')(self._cmd_cancel)
        bridge.command(
            'manual',
            description='Ask before writing, reading or running (on|off)',
        )(self._cmd_manual)

        for index in range(len(self._entries)):
            bridge.on_action(f'{_CALLBACK_PREFIX}{index}')(self._launcher(index))

        bridge.on_action('app.status')(self._act_status)
        bridge.on_action('app.cancel')(self._act_cancel)
        bridge.on_action('approval.yes')(self._act_approve)
        bridge.on_action('approval.no')(self._act_reject)
        bridge.on_message(self._on_message)

    def _panel(self) -> dict:
        if not self._entries:
            return {
                'text': 'No workflows configured. Add a "workflows" list to the '
                        'telegram action to populate this menu.',
            }
        rows = [
            [(entry.label, f'{_CALLBACK_PREFIX}{index}')]
            for index, entry in enumerate(self._entries)
        ]
        rows.append([('Status', 'app.status'), ('Cancel', 'app.cancel')])
        return {'text': 'Control panel:', 'menu': inline_menu(rows)}

    # ── commands and menu actions ────────────────────────────────────────

    def _cmd_start(self, ctx, args):
        return self._panel()

    def _cmd_status(self, ctx, args):
        return self._status_text()

    def _cmd_cancel(self, ctx, args):
        return self._cancel()

    def _cmd_manual(self, ctx, args):
        """Set approval gates for this chat, and for the run in progress.

        The bot cannot hold the live setting — it lives in the workflow process
        clayd spawned — so it keeps the chat's *choice* and pushes it into every
        run it starts, including one already running. That is what makes
        `/manual on` typed between turns take effect on the current turn instead
        of the next launch.
        """
        command = approval.parse_command(f'/manual {args}'.strip())
        if command is None or command.error:
            return (command.message if command else '') or approval.USAGE

        if not command.changes:
            return self._approval_text()

        with self._lock:
            for key, value in command.changes:
                self._approval[key] = value
            active = self._active
            settings = dict(self._approval)

        if active is None:
            return f'{self._approval_text()}\n(no workflow running — this '\
                   f'applies to the next one you start)'

        sent = self._push_approval(active, settings)
        if not sent:
            return f'{self._approval_text()}\n(clayd would not accept it — ' \
                   f'the workflow may have finished)'
        return self._approval_text()

    def _approval_text(self) -> str:
        with self._lock:
            settings = dict(self._approval)
        if not settings:
            return 'manual approval: unset — the workflow uses its own default'
        master = settings.get('manual')
        gates = ', '.join(f'{key} {"on" if settings[key] else "off"}'
                          for key in approval.GATES if key in settings)
        state = 'on' if master else ('off' if master is not None else 'unset')
        return f'manual approval {state}' + (f' — {gates}' if gates else '')

    def _push_approval(self, run: 'ActiveRun', settings: dict) -> bool:
        """Send every chosen setting to a running workflow. False if any failed."""
        ok = True
        for key, value in settings.items():
            try:
                response = self._command(
                    lambda client, k=key, v=value:
                    client.set_option(run.wf_id, k, v))
            except DAEMON_ERRORS as error:
                logger.warn(f'telegram: could not set {key} on {run.wf_id}: '
                            f'{error}')
                return False
            ok = ok and bool(response and response.get('ok'))
        return ok

    def _act_status(self, action):
        return self._status_text()

    def _act_cancel(self, action):
        return self._cancel()

    def _act_approve(self, action):
        return self._answer_approval('y')

    def _act_reject(self, action):
        return self._answer_approval('n')

    def _answer_approval(self, text: str):
        """Send a button's answer to the approval prompt that is waiting.

        Guarded on a prompt actually being outstanding: Telegram leaves buttons
        on screen after the message is answered, and a second tap must not
        answer the *next* question with a stale one.
        """
        with self._lock:
            active = self._active
            awaiting = (active is not None and active.awaiting_input
                        and active.prompt_id.endswith(approval.PROMPT_SUFFIX))
        if not awaiting:
            return 'Nothing is waiting for approval.'
        return self._answer_prompt(active, text)

    def _launcher(self, index: int):
        def launch(action):
            chat_id = action.chat_id
            if chat_id is None:
                return None
            return self._launch(chat_id, self._entries[index])
        return launch

    # ── workflow control ─────────────────────────────────────────────────

    def _launch(self, chat_id: int, entry: MenuEntry):
        with self._lock:
            if self._active is not None:
                return (f'"{self._active.label}" is already running. '
                        'Cancel it before starting another.')

            try:
                response = self._command(
                    lambda client: client.start_workflow(entry.path, auto=False))
            except DAEMON_ERRORS as error:
                return f'Could not reach clayd: {error}'

            if not response or not response.get('ok'):
                reason = (response or {}).get('error') or 'unknown error'
                return f'Could not start "{entry.label}": {reason}'

            self._active = ActiveRun(
                wf_id=response['id'],
                label=entry.label,
                chat_id=chat_id,
            )

        return f'Started "{entry.label}" ({response["id"]}).'

    def _cancel(self):
        with self._lock:
            active = self._active

        if active is None:
            return 'Nothing is running.'

        try:
            self._command(lambda client: client.stop_workflow(active.wf_id))
        except DAEMON_ERRORS as error:
            return f'Could not reach clayd: {error}'

        return f'Stopping "{active.label}".'

    def _status_text(self) -> str:
        with self._lock:
            active = self._active

        if active is None:
            return 'Idle — no workflow running.'
        if active.awaiting_input:
            return f'"{active.label}" ({active.wf_id}) is waiting for your reply.'
        return f'"{active.label}" ({active.wf_id}) is running.'

    # ── daemon events ────────────────────────────────────────────────────

    def _on_event(self, event: dict) -> None:
        """Called from the EventSubscriber reader thread."""
        with self._lock:
            active = self._active

        if active is None or event.get('id') != active.wf_id:
            return

        kind = event.get('event')
        if kind == 'prompt':
            self._on_prompt(active, event)
        elif kind == 'workflow':
            self._on_workflow_event(active, event.get('data') or {})
        elif kind == 'finished':
            self._on_finished(active, event)

    def _on_workflow_event(self, run: ActiveRun, data: dict) -> None:
        """Relay one engine event to the chat, as the CLI would draw it."""
        # The first event proves the workflow's event socket is connected,
        # which is what set_option needs and what a push at launch time cannot
        # rely on. Done before rendering so a run cannot reach a write with the
        # chat's settings still unsent.
        with self._lock:
            pending = (dict(self._approval)
                       if self._approval and not run.approval_pushed else None)
            if pending is not None:
                run.approval_pushed = True
        if pending:
            self._push_approval(run, pending)

        if data.get('type') == run_events.BUSY:
            self._on_busy(run, data)
            return

        text = self._renderer.render(data)
        if not text:
            return

        with self._lock:
            run.output.append(text)
        self._batcher.add(text)

    def _on_busy(self, run: ActiveRun, data: dict) -> None:
        """Turn the engine's busy level into a typing hint.

        The queued progress lines go out first. A typing hint arriving in front
        of the lines that explain what is being worked on reads as the bot
        stalling, and the hint is cleared by Telegram the moment a message is
        sent anyway — so raising it before flushing would clear it immediately.
        """
        if not data.get('active'):
            self._typing.stop()
            return
        self._batcher.flush()
        self._typing.start(run.chat_id)

    def _type_hint(self, chat_id) -> None:
        self._bridge.chat_action(chat_id, 'typing')

    def _on_prompt(self, run: ActiveRun, event: dict) -> None:
        # Everything the workflow narrated on its way to this question must
        # land before the question does, or the user answers a prompt whose
        # context arrives afterwards.
        self._typing.stop()
        self._batcher.flush()

        with self._lock:
            run.prompt_id = event.get('prompt_id', '')
            run.awaiting_input = True
        text = event.get('text') or 'Input requested.'
        # An approval carries buttons; an ordinary question does not. Two taps
        # cover the common answers, and per-item rejection stays free text —
        # typing "2 4" already reaches _answer_prompt, so the fine-grained case
        # needs no stateful button toggling to accumulate a selection.
        menu = None
        if run.prompt_id.endswith(approval.PROMPT_SUFFIX):
            menu = inline_menu([[('✅ Approve all', 'approval.yes'),
                                 ('❌ Reject all', 'approval.no')]])
        self._send(run.chat_id, f'{run.label} asks:\n\n{text}', menu=menu)

    def _on_finished(self, run: ActiveRun, event: dict) -> None:
        # Same ordering rule as a prompt: the run's last lines before its
        # closing line. The typing hint goes first either way — a run that
        # crashed mid-action never sent its own active=False.
        self._typing.stop()
        self._batcher.flush()

        status = event.get('status') or 'finished'
        exit_code = event.get('exit_code')

        summary = f'"{run.label}" {status}'
        if exit_code not in (None, 0):
            summary += f' (exit {exit_code})'

        # Not client.tail() — that reads clayd's captured stdout, and the
        # engine no longer prints. Everything the user should see was sent
        # during the run; this is the closing line only.
        with self._lock:
            relayed = len(run.output)
        if not relayed:
            summary += '\n\n(no output)'

        with self._lock:
            if self._active is run:
                self._active = None

        self._send(run.chat_id, summary)

    # ── inbound chat ─────────────────────────────────────────────────────

    def _on_message(self, ctx):
        with self._lock:
            active = self._active
            awaiting = active is not None and active.awaiting_input

        if awaiting:
            return self._answer_prompt(active, ctx.text)

        # A conversational turn is a model call with no workflow behind it, so
        # nothing emits EVT.BUSY and _on_busy never fires. The wait is the same
        # length as any other model call, so the hint is raised here instead.
        # It shares the one keepalive with a running workflow: an overlap ends
        # with the chat's stop(), and the workflow's next action raises it
        # again on its own busy.
        self._typing.start(ctx.chat_id)
        try:
            response = self._chat(ctx.text)
        finally:
            self._typing.stop()
        if response is not None:
            ctx.reply(str(response))
        return None

    def _answer_prompt(self, run: ActiveRun, text: str):
        try:
            response = self._command(
                lambda client: client.send_input(run.wf_id, text))
        except DAEMON_ERRORS as error:
            return f'Could not reach clayd: {error}'

        if not response or not response.get('ok'):
            return 'clayd rejected that input — the workflow may have moved on.'

        with self._lock:
            run.awaiting_input = False
            run.prompt_id = ''
        return None

    def _chat(self, text: str):
        models = app_config.get_models()
        return gopher.fire(text, examples=[], model=models.get('telegram'))

    # ── outbound ─────────────────────────────────────────────────────────

    def _send(self, chat_id, text, menu=None) -> None:
        """Send to the chat, reporting a transport failure instead of raising.

        Every caller is on a reader or drain thread where an exception would
        silently take the thread down and stop all further relaying.
        """
        try:
            self._bridge.send(chat_id, text, menu=menu)
        except Exception as error:
            logger.error(f'telegram: send failed: {error}')

    def _send_batch(self, text: str) -> None:
        """Sink for the batcher, which has no chat of its own."""
        with self._lock:
            active = self._active
        if active is None:
            return
        self._send(active.chat_id, text)

    # ── lifecycle ────────────────────────────────────────────────────────

    def _command(self, call):
        with self._client_factory() as client:
            return call(client)

    def start(self) -> None:
        self._bridge.start()
        self._batcher.start()
        self._subscriber = self._subscriber_factory()
        self._subscriber.on_event(self._on_event)
        self._subscriber.start()

    def stop(self) -> None:
        self._stopped.set()
        # Before the bridge goes down: the keepalive calls through it, and a
        # send on a stopped bridge is an exception on a thread nobody reads.
        self._typing.stop()
        if self._subscriber is not None:
            self._subscriber.stop()
            self._subscriber = None
        self._batcher.stop()
        self._bridge.stop()

    def run_forever(self) -> None:
        self._install_signal_handlers()
        self.start()
        print('Telegram control channel running. Ctrl-C or `clay daemon stop` to exit.')
        try:
            while not self._stopped.wait(1.0):
                pass
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _install_signal_handlers(self) -> None:
        # clayd stops a workflow with SIGTERM; only valid on the main thread.
        def handle(signum, frame):
            self._stopped.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, handle)
            except ValueError:
                pass


@handler_for('telegram')
def handler(action=None, ctx=None):
    token = (os.environ.get('TELEGRAM_BOT_TOKEN') or '').strip()
    if not token:
        raise ValueError(
            'telegram action requires TELEGRAM_BOT_TOKEN — export the bot token '
            'and re-run this workflow')

    allowed_users, allowed_chats = telegram_allowlists()
    entries = menu_entries((action or {}).get('workflows'))
    ensure_daemon()

    bridge = TelegramBridge(
        token,
        allowed_users=allowed_users,
        allowed_chats=allowed_chats,
    )
    bot = TelegramWorkflowBot(bridge, entries)
    bot.run_forever()
    return {'id': (action or {}).get('id'), 'data': 'telegram channel stopped'}
