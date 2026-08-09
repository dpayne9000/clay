"""
telegram_bridge.py
==================

Dependency-free, importable Telegram Bot API module for two-way chat, command
hooks, inline/reply menus, and application actions.

Typical use from another file:

    from telegram_bridge import TelegramBridge, Action, inline_menu

    bot = TelegramBridge(
        "123456:ABC...",
        allowed_users={123456789},
    )

    @bot.command("start", description="Open the main menu")
    def start(ctx, args):
        ctx.reply(
            "Choose an action:",
            menu=inline_menu([
                [("Status", "system.status"), ("Restart", "system.restart")],
            ]),
        )

    @bot.on_action("system.status")
    def status(action):
        bot.send(action.chat_id, get_status())

    @bot.on_message
    def chat(ctx):
        return Action("chat.received", ctx.chat_id, {
            "text": ctx.text,
            "user_id": ctx.user_id,
        })

    bot.start()                  # non-blocking background thread
    bot.send(CHAT_ID, "Online")  # outbound from the parent application
    ...
    bot.stop()

No third-party packages are required.
"""

from __future__ import annotations

import json
import logging
import queue
import ssl
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Sequence


Json = dict[str, Any]
HandlerResult = Any


@dataclass(slots=True)
class Action:
    """An application-level event emitted by Telegram or by a hook."""

    name: str
    chat_id: Optional[int] = None
    data: dict[str, Any] = field(default_factory=dict)
    source: str = "application"
    user_id: Optional[int] = None
    update: Optional[Json] = None


@dataclass(slots=True)
class MessageContext:
    """Convenient wrapper around a Telegram message update."""

    bot: "TelegramBridge"
    update: Json
    message: Json
    chat_id: int
    user_id: Optional[int]
    text: str
    message_id: int
    chat_type: str
    username: Optional[str]
    first_name: Optional[str]

    def reply(
        self,
        text: str,
        *,
        menu: Optional[Json] = None,
        parse_mode: Optional[str] = None,
        preview: bool = False,
        action: Optional[str] = None,
        action_data: Optional[dict[str, Any]] = None,
    ) -> Json:
        return self.bot.send(
            self.chat_id,
            text,
            menu=menu,
            parse_mode=parse_mode,
            preview=preview,
            reply_to=self.message_id,
            action=action,
            action_data=action_data,
        )

    def trigger(self, name: str, **data: Any) -> None:
        self.bot.trigger(
            Action(
                name=name,
                chat_id=self.chat_id,
                user_id=self.user_id,
                data=data,
                source="message",
                update=self.update,
            )
        )


@dataclass(slots=True)
class MenuContext:
    """Context for an inline keyboard callback."""

    bot: "TelegramBridge"
    update: Json
    query: Json
    callback_id: str
    data: str
    chat_id: Optional[int]
    user_id: Optional[int]
    message: Optional[Json]

    def answer(self, text: Optional[str] = None, *, alert: bool = False) -> bool:
        return self.bot.answer_callback(self.callback_id, text=text, alert=alert)

    def send(self, text: str, **kwargs: Any) -> Json:
        if self.chat_id is None:
            raise ValueError("This callback does not contain a chat ID.")
        return self.bot.send(self.chat_id, text, **kwargs)

    def trigger(self, name: str, **data: Any) -> None:
        self.bot.trigger(
            Action(
                name=name,
                chat_id=self.chat_id,
                user_id=self.user_id,
                data=data,
                source="menu",
                update=self.update,
            )
        )


class TelegramAPIError(RuntimeError):
    def __init__(self, method: str, description: str, code: Optional[int] = None):
        self.method = method
        self.description = description
        self.code = code
        suffix = f" ({code})" if code is not None else ""
        super().__init__(f"Telegram API {method} failed{suffix}: {description}")


def inline_menu(
    rows: Sequence[Sequence[tuple[str, str] | dict[str, Any]]],
) -> Json:
    """
    Build an inline button menu.

    Tuple buttons are (label, callback_action). Dict buttons may use Telegram's
    full InlineKeyboardButton fields, such as {"text": "Site", "url": "..."}.
    """
    keyboard: list[list[Json]] = []
    for row in rows:
        built_row: list[Json] = []
        for item in row:
            if isinstance(item, tuple):
                label, callback_data = item
                built_row.append({"text": label, "callback_data": callback_data})
            else:
                built_row.append(dict(item))
        keyboard.append(built_row)
    return {"inline_keyboard": keyboard}


def reply_menu(
    rows: Sequence[Sequence[str]],
    *,
    resize: bool = True,
    one_time: bool = False,
    selective: bool = False,
    placeholder: Optional[str] = None,
) -> Json:
    """Build a persistent Telegram reply keyboard."""
    return {
        "keyboard": [[{"text": text} for text in row] for row in rows],
        "resize_keyboard": resize,
        "one_time_keyboard": one_time,
        "selective": selective,
        "input_field_placeholder": placeholder,
    }


def remove_reply_menu(*, selective: bool = False) -> Json:
    return {"remove_keyboard": True, "selective": selective}


class TelegramBridge:
    """
    Importable Telegram integration.

    Hooks:
        @bot.command("name", description="...")
        @bot.on_message
        @bot.on_menu("action.name")
        @bot.on_action("action.name")
        @bot.on_outbound
        @bot.on_error

    Handler returns:
        None
        Action(...)
        [Action(...), ...]
        "text response"                 # message/menu hooks only
        {"text": "...", "menu": ...}    # message/menu hooks only

    Every inbound message emits "telegram.message.in".
    Every command emits "telegram.command.<name>".
    Every inline menu press emits both:
        "telegram.menu"
        the callback_data itself, e.g. "system.restart"
    Every successful outbound message emits "telegram.message.out".
    """

    def __init__(
        self,
        token: str,
        *,
        allowed_users: Optional[Iterable[int]] = None,
        allowed_chats: Optional[Iterable[int]] = None,
        request_timeout: int = 45,
        poll_timeout: int = 30,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        token = token.strip()
        if not token or ":" not in token:
            raise ValueError("A valid Telegram bot token is required.")

        users = set(allowed_users or ())
        chats = set(allowed_chats or ())
        if not users and not chats:
            raise ValueError(
                "TelegramBridge requires at least one allowed user or chat ID"
            )

        self.token = token
        self.api_base = f"https://api.telegram.org/bot{token}"
        self.allowed_users = users
        self.allowed_chats = chats
        self.request_timeout = request_timeout
        self.poll_timeout = poll_timeout
        self.log = logger or logging.getLogger(__name__)

        self._commands: dict[str, Callable[[MessageContext, str], HandlerResult]] = {}
        self._command_descriptions: dict[str, str] = {}
        self._message_handlers: list[Callable[[MessageContext], HandlerResult]] = []
        self._menu_handlers: dict[str, list[Callable[[MenuContext], HandlerResult]]] = {}
        self._action_handlers: dict[str, list[Callable[[Action], HandlerResult]]] = {}
        self._all_action_handlers: list[Callable[[Action], HandlerResult]] = []
        self._outbound_handlers: list[Callable[[Action], HandlerResult]] = []
        self._error_handlers: list[Callable[[Exception, Optional[Json]], Any]] = []

        self._stop = threading.Event()
        self._started = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self._send_thread: Optional[threading.Thread] = None
        self._send_queue: queue.Queue[tuple[int, str, dict[str, Any]]] = queue.Queue()
        self._action_queue: queue.Queue[Action] = queue.Queue()
        self.me: Json = {}
        self.username = ""

    # ----------------------------- registration -----------------------------

    def command(
        self,
        *names: str,
        description: Optional[str] = None,
    ) -> Callable[[Callable[[MessageContext, str], HandlerResult]], Callable]:
        def decorator(func: Callable[[MessageContext, str], HandlerResult]) -> Callable:
            for name in names:
                normalized = name.strip().lower().lstrip("/")
                if not normalized:
                    raise ValueError("Command name cannot be empty.")
                self._commands[normalized] = func
                if description:
                    self._command_descriptions[normalized] = description
            return func
        return decorator

    def on_message(self, func: Callable[[MessageContext], HandlerResult]) -> Callable:
        self._message_handlers.append(func)
        return func

    def on_menu(
        self, *values: str
    ) -> Callable[[Callable[[MenuContext], HandlerResult]], Callable]:
        def decorator(func: Callable[[MenuContext], HandlerResult]) -> Callable:
            for value in values:
                self._menu_handlers.setdefault(value, []).append(func)
            return func
        return decorator

    def on_action(
        self, *names: str
    ) -> Callable[[Callable[[Action], HandlerResult]], Callable]:
        def decorator(func: Callable[[Action], HandlerResult]) -> Callable:
            if names:
                for name in names:
                    self._action_handlers.setdefault(name, []).append(func)
            else:
                self._all_action_handlers.append(func)
            return func
        return decorator

    def on_outbound(self, func: Callable[[Action], HandlerResult]) -> Callable:
        self._outbound_handlers.append(func)
        return func

    def on_error(
        self, func: Callable[[Exception, Optional[Json]], Any]
    ) -> Callable:
        self._error_handlers.append(func)
        return func

    # ------------------------------- lifecycle -------------------------------

    @property
    def running(self) -> bool:
        return self._poll_thread is not None and self._poll_thread.is_alive()

    def start(
        self,
        *,
        background: bool = True,
        drop_pending: bool = False,
        register_commands: bool = True,
    ) -> "TelegramBridge":
        if self.running:
            return self

        self._stop.clear()
        self._started.clear()
        self.me = self.get_me()
        self.username = self.me.get("username", "")
        self.delete_webhook(drop_pending=drop_pending)

        if register_commands and self._command_descriptions:
            self.set_commands(
                [(name, description)
                 for name, description in self._command_descriptions.items()]
            )

        self._send_thread = threading.Thread(
            target=self._sender_loop,
            name="telegram-send",
            daemon=True,
        )
        self._send_thread.start()

        if background:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="telegram-poll",
                daemon=True,
            )
            self._poll_thread.start()
            self._started.wait(timeout=5)
        else:
            self._poll_thread = threading.current_thread()
            self._poll_loop()
        return self

    def run_forever(self, **kwargs: Any) -> None:
        self.start(background=False, **kwargs)

    def stop(self, *, wait: bool = True) -> None:
        self._stop.set()
        if wait:
            current = threading.current_thread()
            for thread in (self._poll_thread, self._send_thread):
                if thread and thread is not current and thread.is_alive():
                    thread.join(timeout=self.poll_timeout + 2)

    def __enter__(self) -> "TelegramBridge":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()

    # ----------------------------- public actions ----------------------------

    def trigger(self, action: Action | str, **data: Any) -> None:
        """Dispatch an application action immediately and enqueue it for polling."""
        if isinstance(action, str):
            action = Action(action, data=data)
        elif data:
            action.data.update(data)

        self._action_queue.put(action)

        handlers = [
            *self._action_handlers.get(action.name, ()),
            *self._all_action_handlers,
        ]
        for handler in handlers:
            try:
                self._consume_result(handler(action), action.chat_id, action.user_id)
            except Exception as exc:
                self._handle_error(exc, action.update)

    def get_action(self, timeout: Optional[float] = None) -> Optional[Action]:
        """
        Retrieve the next emitted action. Useful when the parent application
        prefers a polling/event-loop integration instead of decorators.
        """
        try:
            return self._action_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ------------------------------ outbound API -----------------------------

    def send(
        self,
        chat_id: int,
        text: Any,
        *,
        menu: Optional[Json] = None,
        parse_mode: Optional[str] = None,
        preview: bool = False,
        reply_to: Optional[int] = None,
        action: Optional[str] = None,
        action_data: Optional[dict[str, Any]] = None,
    ) -> Json:
        text = str(text)
        result: Json = {}

        for index, chunk in enumerate(self._split_text(text, 4096)):
            result = self.api(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": parse_mode,
                    "link_preview_options": {"is_disabled": not preview},
                    "reply_parameters": (
                        {"message_id": reply_to}
                        if reply_to is not None and index == 0
                        else None
                    ),
                    "reply_markup": menu if index == len(self._split_text(text, 4096)) - 1 else None,
                },
            )

        emitted = Action(
            name=action or "telegram.message.out",
            chat_id=chat_id,
            data={
                "text": text,
                "message": result,
                **(action_data or {}),
            },
            source="outbound",
        )
        self.trigger(emitted)
        for handler in self._outbound_handlers:
            try:
                self._consume_result(handler(emitted), chat_id, None)
            except Exception as exc:
                self._handle_error(exc, None)
        return result

    def send_async(self, chat_id: int, text: Any, **kwargs: Any) -> None:
        self._send_queue.put((chat_id, str(text), kwargs))

    def send_menu(
        self,
        chat_id: int,
        text: str,
        rows: Sequence[Sequence[tuple[str, str] | dict[str, Any]]],
        **kwargs: Any,
    ) -> Json:
        return self.send(chat_id, text, menu=inline_menu(rows), **kwargs)

    def chat_action(self, chat_id: int, action: str = "typing") -> bool:
        """Show one of Telegram's transient status hints in a chat.

        Telegram clears it after about five seconds, or as soon as the bot
        sends a message — whichever comes first. A wait longer than that has to
        re-send, so this is a single call and the repeating is the caller's.
        """
        return bool(self.api("sendChatAction",
                             {"chat_id": chat_id, "action": action}))

    def answer_callback(
        self,
        callback_id: str,
        *,
        text: Optional[str] = None,
        alert: bool = False,
    ) -> bool:
        return bool(
            self.api(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback_id,
                    "text": text,
                    "show_alert": alert,
                },
            )
        )

    # ------------------------------ Telegram API -----------------------------

    def api(self, method: str, payload: Optional[Json] = None) -> Any:
        encoded = urllib.parse.urlencode(
            {
                key: (
                    json.dumps(value, separators=(",", ":"))
                    if isinstance(value, (dict, list, bool))
                    else value
                )
                for key, value in (payload or {}).items()
                if value is not None
            }
        ).encode()

        request = urllib.request.Request(
            f"{self.api_base}/{method}",
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.request_timeout,
                context=ssl.create_default_context(),
            ) as response:
                body = response.read().decode()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            try:
                error = json.loads(body)
            except json.JSONDecodeError:
                raise TelegramAPIError(method, body, exc.code) from exc
            raise TelegramAPIError(
                method,
                error.get("description", body),
                error.get("error_code", exc.code),
            ) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Telegram connection failed: {exc.reason}") from exc

        try:
            response = json.loads(body)
        except json.JSONDecodeError as exc:
            raise TelegramAPIError(method, f"Invalid JSON: {body[:300]}") from exc

        if not response.get("ok"):
            raise TelegramAPIError(
                method,
                response.get("description", "Unknown API error"),
                response.get("error_code"),
            )
        return response.get("result")

    def get_me(self) -> Json:
        return self.api("getMe")

    def delete_webhook(self, *, drop_pending: bool = False) -> bool:
        return bool(self.api("deleteWebhook", {
            "drop_pending_updates": drop_pending,
        }))

    def set_commands(self, commands: Sequence[tuple[str, str]]) -> bool:
        return bool(self.api("setMyCommands", {
            "commands": [
                {"command": name.lstrip("/"), "description": description}
                for name, description in commands
            ],
        }))

    # ------------------------------- internals -------------------------------

    def _poll_loop(self) -> None:
        offset: Optional[int] = None
        retry = 1.0
        self._started.set()
        self.log.info("Telegram bot @%s started", self.username)

        while not self._stop.is_set():
            try:
                updates: list[Json] = self.api("getUpdates", {
                    "offset": offset,
                    "timeout": self.poll_timeout,
                    "limit": 100,
                    "allowed_updates": [
                        "message",
                        "edited_message",
                        "callback_query",
                    ],
                })
                retry = 1.0
                for update in updates:
                    offset = int(update["update_id"]) + 1
                    try:
                        self._dispatch(update)
                    except Exception as exc:
                        self._handle_error(exc, update)
            except Exception as exc:
                self._handle_error(exc, None)
                self._stop.wait(retry)
                retry = min(retry * 2, 30.0)

    def _sender_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chat_id, text, kwargs = self._send_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self.send(chat_id, text, **kwargs)
            except Exception as exc:
                self._handle_error(exc, None)
            finally:
                self._send_queue.task_done()

    def _dispatch(self, update: Json) -> None:
        message = update.get("message") or update.get("edited_message")
        if message:
            self._dispatch_message(update, message)
            return

        query = update.get("callback_query")
        if query:
            self._dispatch_menu(update, query)

    def _dispatch_message(self, update: Json, message: Json) -> None:
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = int(chat["id"])
        user_id = int(sender["id"]) if sender.get("id") is not None else None

        if not self._allowed(user_id, chat_id):
            self.log.warning("Rejected Telegram user=%s chat=%s", user_id, chat_id)
            return

        ctx = MessageContext(
            bot=self,
            update=update,
            message=message,
            chat_id=chat_id,
            user_id=user_id,
            text=message.get("text") or message.get("caption") or "",
            message_id=int(message["message_id"]),
            chat_type=chat.get("type", "unknown"),
            username=sender.get("username"),
            first_name=sender.get("first_name"),
        )

        self.trigger(Action(
            "telegram.message.in",
            chat_id=chat_id,
            user_id=user_id,
            source="message",
            data={
                "text": ctx.text,
                "message_id": ctx.message_id,
                "chat_type": ctx.chat_type,
                "username": ctx.username,
                "first_name": ctx.first_name,
            },
            update=update,
        ))

        if ctx.text.startswith("/"):
            token, _, args = ctx.text.partition(" ")
            command_token = token[1:]
            name, at, target = command_token.partition("@")
            name = name.lower()

            if at and self.username and target.lower() != self.username.lower():
                return

            self.trigger(Action(
                f"telegram.command.{name}",
                chat_id=chat_id,
                user_id=user_id,
                source="command",
                data={"args": args.strip(), "context": ctx},
                update=update,
            ))

            handler = self._commands.get(name)
            if handler:
                self._consume_result(handler(ctx, args.strip()), chat_id, user_id)
                return

        for handler in self._message_handlers:
            self._consume_result(handler(ctx), chat_id, user_id)

    def _dispatch_menu(self, update: Json, query: Json) -> None:
        sender = query.get("from") or {}
        message = query.get("message")
        chat_id = (
            int(message["chat"]["id"])
            if message and message.get("chat")
            else None
        )
        user_id = int(sender["id"]) if sender.get("id") is not None else None
        data = query.get("data") or ""

        if not self._allowed(user_id, chat_id):
            self.answer_callback(
                query["id"],
                text="Not authorized.",
                alert=True,
            )
            return

        ctx = MenuContext(
            bot=self,
            update=update,
            query=query,
            callback_id=query["id"],
            data=data,
            chat_id=chat_id,
            user_id=user_id,
            message=message,
        )

        self.trigger(Action(
            "telegram.menu",
            chat_id=chat_id,
            user_id=user_id,
            source="menu",
            data={"selection": data, "context": ctx},
            update=update,
        ))
        self.trigger(Action(
            data,
            chat_id=chat_id,
            user_id=user_id,
            source="menu",
            data={"context": ctx},
            update=update,
        ))

        handlers = self._menu_handlers.get(data, ())
        if not handlers:
            self.answer_callback(query["id"])
            return

        for handler in handlers:
            self._consume_result(handler(ctx), chat_id, user_id)

    def _consume_result(
        self,
        result: HandlerResult,
        chat_id: Optional[int],
        user_id: Optional[int],
    ) -> None:
        if result is None:
            return

        if isinstance(result, Action):
            if result.chat_id is None:
                result.chat_id = chat_id
            if result.user_id is None:
                result.user_id = user_id
            self.trigger(result)
            return

        if isinstance(result, str):
            if chat_id is not None:
                self.send(chat_id, result)
            return

        if isinstance(result, dict):
            if "name" in result and "text" not in result:
                self.trigger(Action(
                    name=str(result["name"]),
                    chat_id=result.get("chat_id", chat_id),
                    user_id=result.get("user_id", user_id),
                    data=dict(result.get("data") or {}),
                ))
            elif chat_id is not None and "text" in result:
                options = dict(result)
                text = options.pop("text")
                self.send(chat_id, text, **options)
            return

        if isinstance(result, Iterable) and not isinstance(result, (bytes, bytearray)):
            for item in result:
                self._consume_result(item, chat_id, user_id)

    def _allowed(self, user_id: Optional[int], chat_id: Optional[int]) -> bool:
        if self.allowed_users and user_id not in self.allowed_users:
            return False
        if self.allowed_chats and chat_id not in self.allowed_chats:
            return False
        return True

    def _handle_error(self, exc: Exception, update: Optional[Json]) -> None:
        self.log.error("%s", exc)
        self.log.debug("%s", traceback.format_exc())
        for handler in self._error_handlers:
            try:
                handler(exc, update)
            except Exception:
                self.log.exception("Telegram error handler failed")

    @staticmethod
    def _split_text(text: str, limit: int) -> list[str]:
        if not text:
            return [" "]
        chunks: list[str] = []
        remaining = text
        while len(remaining) > limit:
            cut = remaining.rfind("\n", 0, limit + 1)
            if cut < limit // 2:
                cut = remaining.rfind(" ", 0, limit + 1)
            if cut < limit // 2:
                cut = limit
            chunks.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
        chunks.append(remaining)
        return chunks


__all__ = [
    "Action",
    "MessageContext",
    "MenuContext",
    "TelegramAPIError",
    "TelegramBridge",
    "inline_menu",
    "reply_menu",
    "remove_reply_menu",
]
