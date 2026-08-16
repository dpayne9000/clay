"""Render all themed terminal output for Clay."""
import sys
import threading
import time


def intro_effects(theme: dict):
    """Render the short aurora intro animation.

    The caller runs this function on a daemon thread. It hides the cursor,
    animates one line, erases that line, and restores the cursor.
    """
    if theme.get('FEATURE_CURSOR_HIDE', 'true') == 'true':
        sys.stdout.write('\033[?25l')
        sys.stdout.flush()

    aurora = theme.get('SYM_AURORA', '◈')
    label  = 'c l a y'
    codes  = theme.get('SHIMMER_FRAMES', '96 92 95 94 97 96').split()
    ms     = int(theme.get('SHIMMER_FRAME_MS', '80')) / 1000.0

    for code in codes:
        sys.stdout.write(f'\r  \033[{code}m{aurora}  {label}\033[0m')
        sys.stdout.flush()
        time.sleep(ms)

    # Erase the animation before printing the startup banner.
    sys.stdout.write('\033[2K\r')

    if theme.get('FEATURE_CURSOR_HIDE', 'true') == 'true':
        sys.stdout.write('\033[?25h')
    sys.stdout.flush()


def _c(theme: dict, key: str, rich: bool) -> str:
    """Return ANSI escape for theme colour key, or empty string in plain mode."""
    if not rich:
        return ''
    code = theme.get(key, '')
    return f'\033[{code}m' if code else ''


RST = '\033[0m'


def _rst(rich: bool) -> str:
    return RST if rich else ''


def startup_banner(label: str, auto: bool, log_path: str, theme: dict, rich: bool):
    """Print (and optionally animate) the startup banner."""
    if not rich:
        # Preserve the established plain-output format.
        divider = '═' * 56
        print(f'\n{divider}')
        print(f'  {label}' + ('  [auto]' if auto else ''))
        print(f'  log → {log_path}')
        print(divider)
        return

    W = int(theme.get('BANNER_WIDTH', '52'))
    H = theme.get('SYM_BANNER_H', '═')
    TL = theme.get('SYM_CORNER_TL', '╔')
    TR = theme.get('SYM_CORNER_TR', '╗')
    BL = theme.get('SYM_CORNER_BL', '╚')
    BR = theme.get('SYM_CORNER_BR', '╝')
    aurora = theme.get('SYM_AURORA', '◈')
    auto_tag = '  [auto]' if auto else ''

    name_line  = f'{aurora}  c l a y{auto_tag}'
    sub_line   = 'workflow engine'
    run_line   = label[:W - 4]
    log_line   = f'log → {log_path}'[:W - 4]

    def _render(border_col: str) -> list:
        cb = border_col
        cn = _c(theme, 'COLOR_ACTION', rich)
        cd = _c(theme, 'COLOR_DIM', rich)
        r  = _rst(rich)
        lines = [
            f'  {cb}{TL}{H * W}{TR}{r}',
            f'  {cb}║{r}  {cn}{name_line:<{W - 2}}{r}{cb}║{r}',
            f'  {cb}║{r}  {cd}{sub_line:<{W - 4}}{r}  {cb}║{r}',
            f'  {cb}║{r}  {cd}{run_line:<{W - 4}}{r}  {cb}║{r}',
            f'  {cb}║{r}  {cd}{log_line:<{W - 4}}{r}  {cb}║{r}',
            f'  {cb}{BL}{H * W}{BR}{r}',
        ]
        return lines

    n_lines = 6

    if theme.get('FEATURE_SHIMMER', 'true') == 'true' and theme.get('SHIMMER_ENABLED', 'true') == 'true':
        shimmer_codes = theme.get('SHIMMER_FRAMES', '96 92 95 94 97 96').split()
        frame_ms = int(theme.get('SHIMMER_FRAME_MS', '80')) / 1000.0

        if theme.get('FEATURE_CURSOR_HIDE', 'true') == 'true':
            sys.stdout.write('\033[?25l')

        # Print the initial animation frame.
        initial_col = f'\033[{shimmer_codes[0]}m' if shimmer_codes else ''
        for line in _render(initial_col):
            print(line)
        sys.stdout.flush()

        def _shimmer():
            try:
                for code in shimmer_codes[1:]:
                    time.sleep(frame_ms)
                    col = f'\033[{code}m'
                    rendered = _render(col)
                    # Move upward and replace the previous animation frame.
                    sys.stdout.write(f'\033[{n_lines}A')
                    for line in rendered:
                        sys.stdout.write('\033[2K\r' + line + '\n')
                    sys.stdout.flush()
            finally:
                if theme.get('FEATURE_CURSOR_HIDE', 'true') == 'true':
                    sys.stdout.write('\033[?25h')
                    sys.stdout.flush()

        t = threading.Thread(target=_shimmer, daemon=True)
        t.start()
        t.join()  # Finish the animation before workflow output begins.
    else:
        border_col = _c(theme, 'COLOR_BORDER', rich)
        for line in _render(border_col):
            print(line)
    print()


def step_header(name: str, theme: dict, rich: bool):
    """Print a step divider line."""
    if not rich:
        # Preserve the established plain-output format.
        print(f'\n── {name} {"─" * max(1, 44 - len(name))}')
        return
    W = int(theme.get('STEP_RULE_WIDTH', '46'))
    trail = theme.get('SYM_STEP_TRAIL', '─')
    aurora = theme.get('SYM_AURORA', '◈')
    cb = _c(theme, 'COLOR_BORDER', rich)
    cn = _c(theme, 'COLOR_STEP', rich)
    cm = _c(theme, 'COLOR_WARN', rich)
    r  = _rst(rich)
    pad = max(1, W - len(name) - 4)
    print(f'\n{cb}{trail}{trail}{r} {cn}{name}{r} {cb}{trail * pad}{r} {cm}{aurora}{r} {cb}{trail}{trail}{r}')


def action_line(action_type: str, action_id: str, detail: str, theme: dict, rich: bool):
    """Print the action execution bullet."""
    sym = theme.get('SYM_ACTION', '▸')
    ca = _c(theme, 'COLOR_ACTION', rich)
    cw = _c(theme, 'COLOR_STEP', rich)
    cd = _c(theme, 'COLOR_DIM', rich)
    cb = _c(theme, 'COLOR_BORDER', rich)
    r  = _rst(rich)
    id_part     = f'  {cd}→{r} {cb}{action_id}{r}' if action_id else ''
    detail_part = f'  {cd}{detail}{r}' if detail else ''
    print(f'  {ca}{sym}{r} {cw}{action_type}{r}{id_part}{detail_part}')


def scramda_input(prompt_text: str, theme: dict, rich: bool, model: str = ''):
    """Show the prompt being sent to the AI (rich mode only)."""
    if not rich or theme.get('FEATURE_SCRAMDA_INPUT_BOX', 'true') != 'true':
        return
    # Preserve line breaks. The renderer applies display.promptMaxChars before
    # this function; themes control presentation, not content limits.
    indent = theme.get('RESPONSE_INDENT', '  ')
    top_sym = theme.get('SYM_RESPONSE_TOP', '┄')
    aurora  = theme.get('SYM_AURORA', '◈')
    cb = _c(theme, 'COLOR_PROMPT_BOX', rich)
    r  = _rst(rich)
    body = prompt_text
    rule = top_sym * 46
    model_tag = f' [{model}]' if model else ''
    print(f'{indent}{cb}{top_sym} {aurora} prompt{model_tag} {rule}{r}')
    for line in body.splitlines() or ['']:
        print(f'{indent}{cb}{line}{r}')
    print(f'{indent}{cb}{rule}{r}')


def scramda_output(text: str, theme: dict, rich: bool):
    """Show the AI response (styled in rich mode, plain print otherwise)."""
    indent = theme.get('RESPONSE_INDENT', '  ')
    if not rich or theme.get('FEATURE_SCRAMDA_OUTPUT_BOX', 'true') != 'true':
        print(text)
        return
    top_sym = theme.get('SYM_RESPONSE_TOP', '┄')
    bot_sym = theme.get('SYM_RESPONSE_BOTTOM', '╌')
    aurora  = theme.get('SYM_AURORA', '◈')
    ch = _c(theme, 'COLOR_BORDER', rich)
    cg = _c(theme, 'COLOR_ACTION', rich)
    cr = _c(theme, 'COLOR_RESPONSE', rich)
    cd = _c(theme, 'COLOR_DIM', rich)
    r  = _rst(rich)
    rule = top_sym * 46
    bot_rule = bot_sym * 48
    print(f'{indent}{ch}{top_sym} {cg}{aurora} response{ch} {rule}{r}')
    for line in text.splitlines():
        print(f'{indent}{cr}{line}{r}')
    print(f'{indent}{cd}{bot_rule}{r}')


def error(msg: str, theme: dict, rich: bool):
    sym = theme.get('SYM_ERROR', '✕')
    ce = _c(theme, 'COLOR_ERROR', rich)
    r  = _rst(rich)
    if rich:
        print(f'  {ce}{sym} {msg}{r}')
    else:
        print(f'  !! {msg}')


def warn(msg: str, theme: dict, rich: bool):
    sym = theme.get('SYM_WARN', '⚡')
    cw = _c(theme, 'COLOR_WARN', rich)
    r  = _rst(rich)
    if rich:
        print(f'  {cw}{sym} {msg}{r}')
    else:
        print(f'  warning: {msg}')


def command_echo(command: str, outcome: str, theme: dict, rich: bool):
    """Render a session command and its result.

    Use a distinct style so setting changes cannot look like workflow answers.
    Repeat the command and indent its result to preserve their association.
    """
    sym = theme.get('SYM_COMMAND', '»')
    cc = _c(theme, 'COLOR_COMMAND', rich)
    cd = _c(theme, 'COLOR_DIM', rich)
    r  = _rst(rich)
    if rich:
        print(f'\n  {cc}{sym} {command}{r}')
        for line in str(outcome).splitlines():
            print(f'    {cd}{line}{r}')
    else:
        print(f'\n  > {command}')
        for line in str(outcome).splitlines():
            print(f'    {line}')


# ── concise mode ─────────────────────────────────────────────────────────
#
# Concise-mode functions style labels supplied by actions without rewriting
# them. Actions remain responsible for describing what they did.


def file_write(label: str, diff: str, theme: dict, rich: bool):
    """Render a written-file label and an optional diff.

    New files use one line because their content was already displayed. Edited
    files include a diff because only the changed lines are new information.
    """
    sym = theme.get('SYM_FILE', '✎')
    cf = _c(theme, 'COLOR_ACTION', rich)
    r  = _rst(rich)
    print(f'  {cf}{sym}{r} {label}' if rich else f'  {sym} {label}')
    if diff:
        _diff_lines(diff, theme, rich)


def _diff_lines(diff: str, theme: dict, rich: bool):
    """Render an indented, colored unified diff without file headers.

    Omit the before/after headers because the preceding label identifies the
    file and the header prefixes resemble changed lines.
    """
    add = _c(theme, 'COLOR_DIFF_ADD', rich)
    rem = _c(theme, 'COLOR_DIFF_DEL', rich)
    dim = _c(theme, 'COLOR_DIM', rich)
    r   = _rst(rich)
    for line in str(diff).splitlines():
        if line.startswith('---') or line.startswith('+++'):
            continue
        if line.startswith('@@'):
            colour = dim
        elif line.startswith('+'):
            colour = add
        elif line.startswith('-'):
            colour = rem
        else:
            colour = ''
        print(f'      {colour}{line}{r}' if colour else f'      {line}')


def file_read(label: str, theme: dict, rich: bool):
    """Render one line naming content loaded by an action.

    Display the source name but not content that already exists on disk.
    """
    sym = theme.get('SYM_READ', '▪')
    cd = _c(theme, 'COLOR_DIM', rich)
    r  = _rst(rich)
    print(f'  {cd}{sym} {label}{r}' if rich else f'  {sym} {label}')


def shell_run(command: str, output: str, theme: dict, rich: bool):
    """Render a workflow command with indented output.

    This style differs from command_echo(), which represents a session command
    typed by the user rather than a command executed by the workflow.
    """
    cc = _c(theme, 'COLOR_COMMAND', rich)
    cd = _c(theme, 'COLOR_DIM', rich)
    r  = _rst(rich)
    print(f'  {cc}{command}{r}' if rich else f'  {command}')
    for line in str(output or '').splitlines():
        print(f'      {cd}{line}{r}' if rich else f'      {line}')


def completion_banner(log_path: str, theme: dict, rich: bool):
    """Print the workflow completion banner."""
    W = int(theme.get('BANNER_WIDTH', '52'))
    H = theme.get('SYM_BANNER_H', '═')
    TL = theme.get('SYM_CORNER_TL', '╔')
    TR = theme.get('SYM_CORNER_TR', '╗')
    BL = theme.get('SYM_CORNER_BL', '╚')
    BR = theme.get('SYM_CORNER_BR', '╝')
    done_sym = theme.get('SYM_DONE', '✓')
    cb  = _c(theme, 'COLOR_DONE', rich)
    cd  = _c(theme, 'COLOR_DIM', rich)
    r   = _rst(rich)
    done_text = f'{done_sym}  done'
    log_text  = f'log → {log_path}'[:W - 4]
    print()
    if rich:
        print(f'  {cb}{TL}{H * W}{TR}{r}')
        print(f'  {cb}║{r}  {cb}{done_text:<{W - 2}}{r}{cb}║{r}')
        print(f'  {cb}║{r}  {cd}{log_text:<{W - 4}}{r}  {cb}║{r}')
        print(f'  {cb}{BL}{H * W}{BR}{r}')
    else:
        print(f'  {"═" * (W + 2)}')
        print(f'  {done_text}')
        print(f'  {log_text}')
        print(f'  {"═" * (W + 2)}')
    print()
