import os
import subprocess
import tempfile
from ...run import approval, logger
from ..registry import action, req, opt, handler_for


@action('runCode', skeleton=False)
class RunCode:
    id:        str = req("Output key for stdout")
    language:  str = opt("Interpreter: python, bash, node, sh", "python")
    source:    str = opt("Inline source code string", None)
    sourceKey: str = opt("Context key holding the source code. Takes precedence over source", None)
    stdin:     str = opt("Context key whose value is piped as stdin to the process", None)
    timeout:   int = opt("Seconds before the process is killed", 30)


_INTERPRETERS = {
    'python': ['python3'],
    'bash':   ['bash'],
    'node':   ['node'],
    'sh':     ['sh'],
}

_EXTENSIONS = {
    'python': '.py',
    'bash':   '.sh',
    'node':   '.js',
    'sh':     '.sh',
}


@handler_for('runCode')
def handler(action, ctx, daemon=False):
    language = (action.get('language') or 'python').lower()
    interpreter = _INTERPRETERS.get(language)
    if not interpreter:
        logger.error(f"runCode: unsupported language '{language}'")
        return None

    # Resolve source: inline or from a previous_data key (AI-generated)
    source_key = action.get('sourceKey')
    if source_key:
        source = ctx.get(source_key)
        if source is None:
            logger.error(f"runCode: no data for sourceKey '{source_key}'")
            return None
    else:
        source = action.get('source')
        if not source:
            logger.error("runCode: no 'source' or 'sourceKey' provided")
            return None

    decision = approval.confirm(
        'commands', f'runCode wants to execute generated {language} source:',
        [(language, str(source))],
        prompt_id=f'{action.get("id", "")}.approve', required=True)
    if not decision:
        return {"id": action.get("id"), "data": None,
                "error": "runCode: generated source was not approved"}

    stdin_key = action.get('stdin')
    stdin_data = str(ctx[stdin_key]) if stdin_key and stdin_key in ctx else None

    timeout = action.get('timeout', 30)
    ext = _EXTENSIONS.get(language, '.tmp')

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix=ext, delete=False) as tmp:
            tmp.write(str(source))
            tmp_path = tmp.name

        result = subprocess.run(
            interpreter + [tmp_path],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.returncode != 0:
            stderr_preview = result.stderr.strip()[:200]
            logger.warn(f"runCode exit {result.returncode}: {stderr_preview}")
            output = output + f"\n[exit code: {result.returncode}]"

    except subprocess.TimeoutExpired:
        logger.warn(f"runCode: timeout after {timeout}s")
        output = f"[timeout after {timeout}s]"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return {"id": action.get("id"), "data": output}
