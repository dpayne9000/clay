import json
import os
import urllib.parse
from html.parser import HTMLParser
from ...run import logger
from ...lib import config
from ...lib.network_policy import NetworkPolicyError, request, validate_url
from ..registry import action, req, opt, handler_for


@action('browseWeb', skeleton=False)
class BrowseWeb:
    id:       str = req("Output key for the extracted page text")
    url:      str = opt("URL to fetch (http/https only). Supports {placeholder} interpolation", None)
    urlsKey:  str = opt("Context key holding newline-separated URLs. Each is fetched and returned as its own labelled block", None)
    maxPages: int = opt("Maximum URLs read from urlsKey", 3)
    maxChars: int = opt("Maximum characters of extracted text per page", 4000)
    siteKey:  str = opt("If set, saves URL and 500-char preview to webactions/{siteKey}.json", None)


@action('searchWeb', skeleton=False)
class SearchWeb:
    id:         str = req("Output key for the formatted numbered result list")
    query:      str = opt("Search query string. Supports {placeholder} interpolation", None)
    queryKey:   str = opt("Context key holding the query. Takes precedence over query", None)
    engine:     str = opt("Search engine: duckduckgo (keyless), duckduckgo-instant, google, or bing", "duckduckgo")
    maxResults: int = opt("Maximum results to return", 5)
    apiKey:     str = opt("Required for google and bing engines", None)
    cx:         str = opt("Custom Search Engine ID — required for google engine", None)


@action('listSites', skeleton=False)
class ListSites:
    id: str = req("Output key for newline-separated .json filenames in webactions/")


@action('loadSite', skeleton=False)
class LoadSite:
    id:      str = req("Output key for the site profile JSON string")
    siteKey: str = req("Filename stem in webactions/ (without .json)")


WEBACTIONS_BASE = config.user_path('webactions')

# Schemes the agent is allowed to fetch.  No file://, no ftp://, no internal schemes.
_ALLOWED_SCHEMES = frozenset({'http', 'https'})

# Maximum bytes read from a remote HTTP response before decoding.
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB

def _safe_site_key_path(site_key: str):
    """Resolve siteKey to a path inside WEBACTIONS_BASE, or None if it would escape."""
    real_base = os.path.realpath(WEBACTIONS_BASE)
    candidate = os.path.realpath(os.path.join(WEBACTIONS_BASE, f"{site_key}.json"))
    if not candidate.startswith(real_base + os.sep):
        return None
    return candidate


class _TextExtractor(HTMLParser):
    """Strip tags and return visible text."""

    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'head'):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'head'):
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data):
        if not self._skip_depth:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self):
        return '\n'.join(self._parts)


class _SafeMap(dict):
    def __missing__(self, key):
        return f'{{{key}}}'


# ---------------------------------------------------------------------------
# browseWeb
# ---------------------------------------------------------------------------

def _refusal_for(url: str):
    """Why this URL may not be fetched, or None if it may.

    One gate for both the single-URL and the multi-URL path. A second copy is
    how the two would come to disagree about what is allowed.
    """
    try:
        validate_url(url)
    except NetworkPolicyError as exc:
        return str(exc)
    return None


def _read_page(url: str, max_chars: int) -> str:
    """Fetch one URL and return its extracted text, or a bracketed error.

    Never raises: a page that fails is one source lost, and a turn reading
    three of them should not end because the second was a 404.
    """
    try:
        response = request(
            'GET', url, headers={'User-Agent': 'clay/1.0'},
            max_bytes=_MAX_RESPONSE_BYTES)
        content_type = response.headers.get('Content-Type', '')
        raw = response.text
    except Exception as e:
        logger.warn(f"browseWeb error: {e}")
        return f"[error: {e}]"

    if 'html' in content_type.lower():
        parser = _TextExtractor()
        parser.feed(raw)
        text = parser.get_text()
    else:
        text = raw

    output = text[:max_chars]
    if len(text) > max_chars:
        output += f'\n[... truncated at {max_chars} chars]'
    return output


def _urls_from(action, ctx):
    """The URLs to read, from urlsKey if given, else the single url field.

    Returns (urls, error). urlsKey wins when both are present rather than being
    merged with `url`: they are two ways of saying the same thing, and guessing
    which the workflow meant is worse than honouring the more specific one.
    """
    urls_key = action.get('urlsKey')
    if urls_key:
        raw = ctx.get(urls_key) or ''
        urls = [line.strip() for line in str(raw).splitlines() if line.strip()]
        if not urls:
            return [], f"browseWeb: '{urls_key}' held no URLs"
        return urls[:int(action.get('maxPages', 3))], None

    url = (action.get('url') or '').format_map(_SafeMap(ctx))
    if not url:
        return [], "browseWeb: needs 'url' or 'urlsKey'"
    return [url], None


@handler_for('browseWeb')
def browse_handler(action, ctx):
    urls, error = _urls_from(action, ctx)
    if error:
        logger.error(error)
        return None

    max_chars = int(action.get('maxChars', 4000))
    single = not action.get('urlsKey')

    # One siteKey names one profile file, so several pages would each overwrite
    # the last and the file would hold whichever happened to be read last. The
    # pages are still fetched and returned; only the saving is refused.
    site_key = action.get('siteKey')
    if site_key and not single:
        logger.warn("browseWeb: 'siteKey' names a single profile and is ignored "
                    "with 'urlsKey' — several pages cannot share one profile")
        site_key = None

    blocks = []
    for url in urls:
        refusal = _refusal_for(url)
        if refusal:
            logger.error(f"browseWeb: {refusal}")
            # On the single-URL path a refusal is the whole result, and
            # returning None leaves the workflow's default in place — the
            # honest "nothing was read". On the multi-URL path the other
            # pages still stand, so the refusal is reported beside them.
            if single:
                return None
            blocks.append(f'=== {url} ===\n[refused: {refusal}]')
            continue

        text = _read_page(url, max_chars)
        if site_key:
            _save_site_profile(site_key, url, text)
        blocks.append(text if single else f'=== {url} ===\n{text}')

    return {"id": action.get("id"), "data": '\n\n'.join(blocks)}


# ---------------------------------------------------------------------------
# listSites
# ---------------------------------------------------------------------------

@handler_for('listSites')
def list_sites_handler(action, ctx):
    if not os.path.isdir(WEBACTIONS_BASE):
        return {"id": action.get("id"), "data": ""}
    files = sorted(f for f in os.listdir(WEBACTIONS_BASE) if f.endswith('.json'))
    return {"id": action.get("id"), "data": '\n'.join(files)}


# ---------------------------------------------------------------------------
# loadSite
# ---------------------------------------------------------------------------

@handler_for('loadSite')
def load_site_handler(action, ctx):
    site_key = action.get('siteKey')
    if not site_key:
        logger.error("loadSite: missing 'siteKey' field")
        return None

    profile_path = _safe_site_key_path(site_key)
    if profile_path is None:
        logger.error(f"loadSite: invalid siteKey '{site_key}' (path traversal detected)")
        return None
    if not os.path.exists(profile_path):
        return {"id": action.get("id"), "data": ""}

    with open(profile_path) as f:
        data = json.load(f)

    return {"id": action.get("id"), "data": json.dumps(data, indent=2)}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# searchWeb
# ---------------------------------------------------------------------------

def _format_results(results):
    """Format a list of {title, url, snippet} dicts into readable text."""
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', '(no title)')}")
        lines.append(f"   {r.get('url', '')}")
        snippet = r.get('snippet', '').replace('\n', ' ').strip()
        if snippet:
            lines.append(f"   {snippet}")
    return '\n'.join(lines)


class _ResultsExtractor(HTMLParser):
    """Pull result links and snippets out of DuckDuckGo's HTML results page.

    Written on the stdlib parser rather than a scraping library because clay's
    core dependencies are `requests` and `dnspython` and a search engine is not
    worth a third. It keys off two stable class names — a link carrying
    `result__a` and a block carrying `result__snippet` — and ignores structure
    entirely, so a layout change costs results rather than raising.
    """

    def __init__(self):
        super().__init__()
        self.results = []
        self._href = None
        self._collecting = None   # 'title' | 'snippet' | None
        self._buffer = []

    @staticmethod
    def _classes(attrs):
        for name, value in attrs:
            if name == 'class':
                return (value or '').split()
        return []

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        if tag == 'a' and 'result__a' in classes:
            self._flush()
            self._href = dict(attrs).get('href')
            self._collecting = 'title'
        elif 'result__snippet' in classes:
            self._collecting = 'snippet'

    def handle_endtag(self, tag):
        if self._collecting == 'title' and tag == 'a':
            self._commit_title()
        elif self._collecting == 'snippet':
            self._commit_snippet()

    def handle_data(self, data):
        if self._collecting:
            stripped = data.strip()
            if stripped:
                self._buffer.append(stripped)

    def _text(self):
        text = ' '.join(self._buffer)
        self._buffer = []
        return text

    def _commit_title(self):
        url = _unwrap_ddg_link(self._href or '')
        title = self._text()
        self._collecting = None
        self._href = None
        if url:
            self.results.append({'title': title, 'url': url, 'snippet': ''})

    def _commit_snippet(self):
        text = self._text()
        self._collecting = None
        # A snippet belongs to the link above it. Without a link it belongs to
        # nothing, so it is dropped rather than attached to the previous result.
        if self.results and not self.results[-1]['snippet']:
            self.results[-1]['snippet'] = text

    def _flush(self):
        self._buffer = []
        self._collecting = None

    def close(self):
        super().close()
        if self._collecting == 'title':
            self._commit_title()
        elif self._collecting == 'snippet':
            self._commit_snippet()


def _unwrap_ddg_link(href: str) -> str:
    """Return the real destination behind a DuckDuckGo redirect link.

    Results are wrapped as `/l/?uddg=<urlencoded target>`. Handing the wrapper
    to browseWeb would fetch a redirector and extract nothing, so the target is
    recovered here where the shape is known — the URL that reaches the rest of
    the system is always the page itself.
    """
    if not href:
        return ''
    if href.startswith('//'):
        href = 'https:' + href
    parsed = urllib.parse.urlparse(href)
    if parsed.path.startswith('/l/') or 'uddg' in (parsed.query or ''):
        target = urllib.parse.parse_qs(parsed.query).get('uddg')
        if target:
            return target[0]
        return ''
    if parsed.scheme in _ALLOWED_SCHEMES:
        return href
    return ''


def _search_duckduckgo_html(query, max_results):
    """Keyless web search against DuckDuckGo's HTML endpoint.

    This is the engine that makes searchWeb work without credentials. The JSON
    Instant Answer API (see _search_duckduckgo_instant) is not a web search —
    it answers a definitional question and returns nothing at all for most real
    queries — so it cannot be the default behind a field named `engine`.
    """
    data = urllib.parse.urlencode({'q': query}).encode()
    req = urllib.request.Request(
        'https://html.duckduckgo.com/html/',
        data=data,
        headers={
            'User-Agent': 'clay/1.0',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read(_MAX_RESPONSE_BYTES).decode('utf-8', errors='replace')

    parser = _ResultsExtractor()
    parser.feed(html)
    parser.close()

    seen = set()
    results = []
    for item in parser.results:
        if item['url'] in seen:
            continue
        seen.add(item['url'])
        results.append(item)
        if len(results) >= max_results:
            break
    return results


def _search_duckduckgo_instant(query, max_results):
    params = urllib.parse.urlencode({'q': query, 'format': 'json', 'no_html': '1', 'skip_disambig': '1'})
    req = urllib.request.Request(
        f"https://api.duckduckgo.com/?{params}",
        headers={'User-Agent': 'clay/1.0'},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8', errors='replace'))

    results = []
    abstract = data.get('AbstractText', '').strip()
    abstract_url = data.get('AbstractURL', '').strip()
    if abstract and abstract_url:
        results.append({'title': data.get('Heading', 'Abstract'), 'url': abstract_url, 'snippet': abstract})

    for topic in data.get('RelatedTopics', []):
        if len(results) >= max_results:
            break
        # topics can be nested groups
        if 'Topics' in topic:
            for sub in topic['Topics']:
                if len(results) >= max_results:
                    break
                text = sub.get('Text', '')
                url = sub.get('FirstURL', '')
                if text and url:
                    results.append({'title': text[:80], 'url': url, 'snippet': text})
        else:
            text = topic.get('Text', '')
            url = topic.get('FirstURL', '')
            if text and url:
                results.append({'title': text[:80], 'url': url, 'snippet': text})

    return results


def _search_google(query, max_results, api_key, cx):
    params = urllib.parse.urlencode({'q': query, 'key': api_key, 'cx': cx, 'num': min(max_results, 10)})
    req = urllib.request.Request(
        f"https://www.googleapis.com/customsearch/v1?{params}",
        headers={'User-Agent': 'clay/1.0'},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8', errors='replace'))

    results = []
    for item in data.get('items', [])[:max_results]:
        results.append({
            'title': item.get('title', ''),
            'url': item.get('link', ''),
            'snippet': item.get('snippet', ''),
        })
    return results


def _search_bing(query, max_results, api_key):
    params = urllib.parse.urlencode({'q': query, 'count': min(max_results, 50)})
    req = urllib.request.Request(
        f"https://api.bing.microsoft.com/v7.0/search?{params}",
        headers={'User-Agent': 'clay/1.0', 'Ocp-Apim-Subscription-Key': api_key},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8', errors='replace'))

    results = []
    for item in data.get('webPages', {}).get('value', [])[:max_results]:
        results.append({
            'title': item.get('name', ''),
            'url': item.get('url', ''),
            'snippet': item.get('snippet', ''),
        })
    return results


@handler_for('searchWeb')
def search_handler(action, ctx):
    # Resolve query from queryKey or inline query template
    query_key = action.get('queryKey')
    if query_key:
        raw_query = ctx.get(query_key, '')
    else:
        raw_query = action.get('query', '')
        raw_query = raw_query.format_map(_SafeMap(ctx))

    if not raw_query:
        logger.error("searchWeb: missing query")
        return None

    engine = action.get('engine', 'duckduckgo').lower()
    max_results = int(action.get('maxResults', 5))

    try:
        if engine == 'duckduckgo':
            results = _search_duckduckgo_html(raw_query, max_results)
        elif engine == 'duckduckgo-instant':
            results = _search_duckduckgo_instant(raw_query, max_results)
        elif engine == 'google':
            api_key = action.get('apiKey', '')
            cx = action.get('cx', '')
            if not api_key or not cx:
                logger.error("searchWeb(google): missing 'apiKey' or 'cx'")
                return None
            results = _search_google(raw_query, max_results, api_key, cx)
        elif engine == 'bing':
            api_key = action.get('apiKey', '')
            if not api_key:
                logger.error("searchWeb(bing): missing 'apiKey'")
                return None
            results = _search_bing(raw_query, max_results, api_key)
        else:
            logger.error(f"searchWeb: unknown engine '{engine}' "
                         "(use duckduckgo, duckduckgo-instant, google, or bing)")
            return None

        logger.debug(f"searchWeb: {engine} → {len(results)} results for '{raw_query[:60]}'")
        output = _format_results(results) if results else f"[no results for: {raw_query}]"
        return {"id": action.get("id"), "data": output}

    except Exception as e:
        logger.warn(f"searchWeb error ({engine}): {e}")
        return {"id": action.get("id"), "data": f"[error: {e}]"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _save_site_profile(site_key, url, content_preview):
    os.makedirs(WEBACTIONS_BASE, exist_ok=True)
    profile_path = _safe_site_key_path(site_key)
    if profile_path is None:
        logger.error(f"browseWeb: invalid siteKey '{site_key}' (path traversal detected)")
        return

    profile = {"url": url, "preview": content_preview[:500]}
    if os.path.exists(profile_path):
        try:
            with open(profile_path) as f:
                existing = json.load(f)
            existing.update(profile)
            profile = existing
        except Exception as e:
            logger.warn(f"web: error loading site profile {profile_path}: {e} — starting fresh")

    with open(profile_path, 'w') as f:
        json.dump(profile, f, indent=2)
