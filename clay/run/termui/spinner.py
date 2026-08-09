"""Non-blocking terminal spinner with aurora theme support."""
import sys
import threading
import time


class Spinner:
    def __init__(self, theme: dict, rich: bool):
        self._theme = theme
        self._rich = rich
        self._thread = None
        self._stop_event = threading.Event()

    def _c(self, code: str) -> str:
        return f'\033[{code}m' if self._rich and code else ''

    def _erase_line(self):
        sys.stdout.write('\033[2K\r')
        sys.stdout.flush()

    def start(self, label: str = ''):
        if not self._rich:
            return
        label = label or self._theme.get('SPINNER_LABEL', 'processing')
        frames = self._theme.get('SPINNER_FRAMES', '◌ ◎ ● ◎ ◌ ·').split()
        colors = self._theme.get('SPINNER_COLORS', '96 92 95 94 97 96').split()
        interval = int(self._theme.get('SPINNER_INTERVAL_MS', '100')) / 1000.0
        rst = '\033[0m'
        self._stop_event.clear()

        def _run():
            i = 0
            indent = self._theme.get('RESPONSE_INDENT', '  ')
            while not self._stop_event.is_set():
                frame = frames[i % len(frames)]
                col = self._c(colors[i % len(colors)])
                dim = self._c(self._theme.get('COLOR_DIM', '2'))
                sys.stdout.write(f'\r{indent}{col}{frame}{rst} {dim}{label}{rst}')
                sys.stdout.flush()
                time.sleep(interval)
                i += 1

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self):
        if not self._rich:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.3)
        self._erase_line()
