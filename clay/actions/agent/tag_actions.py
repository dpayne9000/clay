"""
deriveTags — shared keyword extraction used by writeMemory, searchSkills,
and any workflow action that needs tags without an AI call.

Algorithm:
  1. Tokenise text (split on whitespace, punctuation, hyphens, underscores)
  2. Remove stopwords and tokens shorter than 3 chars
  3. Score each unique token: sum of (1 + positional_decay) across all occurrences
     — earlier occurrences score higher (title/heading words matter more)
  4. Boost tokens that look like technical identifiers (camelCase split, path segments)
  5. Return top max_tags tokens, sorted by score descending
"""

import re
from ...run import logger
from ..registry import action, req, opt, handler_for


@action('deriveTags', skeleton=False)
class DeriveTags:
    id:         str = req("Output key for the comma-separated tag string")
    contentKey: str = opt("Context key holding the primary text to analyse", None)
    content:    str = opt("Inline fallback text if contentKey is absent or empty", None)
    contextKey: str = opt("Context key for secondary text, weighted at 40% of primary", None)
    maxTags:    int = opt("Maximum number of tags to return", 6)


# ---------------------------------------------------------------------------
# Stopwords
# ---------------------------------------------------------------------------

STOPWORDS = frozenset({
    # articles / conjunctions / prepositions
    'a', 'an', 'the', 'and', 'or', 'but', 'nor', 'so', 'yet', 'both',
    'either', 'neither', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
    'by', 'from', 'as', 'into', 'through', 'during', 'before', 'after',
    'above', 'below', 'between', 'out', 'up', 'about', 'against', 'along',
    'around', 'near', 'off', 'over', 'past', 'per', 'since', 'than',
    'under', 'until', 'upon', 'via', 'within',
    # pronouns
    'i', 'me', 'my', 'we', 'us', 'our', 'you', 'your', 'he', 'him', 'his',
    'she', 'her', 'it', 'its', 'they', 'them', 'their',
    # demonstratives / determiners
    'this', 'that', 'these', 'those', 'all', 'any', 'each', 'every', 'few',
    'more', 'most', 'other', 'some', 'such', 'no', 'not', 'only', 'same',
    # auxiliaries
    'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
    'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
    'must', 'shall', 'can',
    # common verbs too generic to be useful tags
    'get', 'gets', 'got', 'set', 'sets', 'run', 'runs', 'ran', 'make',
    'makes', 'made', 'use', 'used', 'using', 'add', 'added', 'new', 'let',
    'need', 'needs', 'want', 'wants', 'take', 'takes', 'took', 'put', 'puts',
    'go', 'goes', 'went', 'see', 'sees', 'saw', 'know', 'knows', 'knew',
    # common adverbs / fillers
    'also', 'just', 'very', 'too', 'so', 'well', 'now', 'then', 'here',
    'there', 'when', 'where', 'why', 'how', 'what', 'which', 'who', 'whom',
    'if', 'else', 'whether', 'while', 'although', 'because', 'since',
    # numbers / single chars absorbed by length filter
})

# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def _split_technical(token):
    """Split camelCase and path separators into sub-tokens."""
    # camelCase → camel case
    parts = re.sub(r'([a-z])([A-Z])', r'\1 \2', token).lower().split()
    return parts


def derive_tags(text, max_tags=6, extra_context=''):
    """
    Extract the most relevant lowercase keyword tags from text.

    Args:
        text:          main content to analyse
        extra_context: optional secondary text (lower weight)
        max_tags:      maximum number of tags to return

    Returns:
        list of str — unique lowercase keywords, best first
    """
    def _tokenise(src, weight_multiplier=1.0):
        # normalise separators so kebab-names / paths yield individual words
        src = re.sub(r'[-_/\\.]', ' ', src)
        # split camelCase
        src = re.sub(r'([a-z])([A-Z])', r'\1 \2', src)
        raw_tokens = re.findall(r'[a-zA-Z][a-zA-Z0-9]*', src.lower())
        return [(t, weight_multiplier) for t in raw_tokens]

    tokens = _tokenise(text, 1.0)
    if extra_context:
        tokens += _tokenise(extra_context, 0.4)

    n = len(tokens)
    scores = {}
    for i, (tok, wm) in enumerate(tokens):
        if tok in STOPWORDS or len(tok) < 3:
            continue
        # positional decay: tokens near the start score higher
        positional = 1.0 + (n - i) / max(n, 1)
        scores[tok] = scores.get(tok, 0.0) + positional * wm

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [k for k, _ in ranked[:max_tags]]


def tags_to_string(tags):
    """Return comma-separated tag string."""
    return ', '.join(tags)


def tags_from_filename(filename):
    """
    Derive tags from a skill/file filename.
    e.g. 'express-app-scaffold.py' → ['express', 'app', 'scaffold']
    """
    stem = re.sub(r'\.[^.]+$', '', filename)   # strip extension
    parts = re.split(r'[-_.]', stem.lower())
    return [p for p in parts if p and p not in STOPWORDS and len(p) >= 3]


# ---------------------------------------------------------------------------
# deriveTags action handler
# ---------------------------------------------------------------------------

@handler_for('deriveTags')
def handler(action, ctx):
    """
    deriveTags — extract weighted keyword tags from content without an AI call.

    Action fields:
      contentKey   key in ctx holding the main text
      contextKey   optional key for secondary/supporting text (lower weight)
      content      inline text fallback if contentKey is absent
      maxTags      max number of tags to return (default 6)

    Returns comma-separated lowercase tag string stored under id.
    """
    content_key = action.get('contentKey')
    context_key = action.get('contextKey')
    max_tags = int(action.get('maxTags', 6))

    text = ''
    if content_key:
        text = str(ctx.get(content_key, ''))
    if not text:
        text = str(action.get('content', ''))

    if not text.strip():
        logger.error("deriveTags: no content to derive tags from")
        return {"id": action.get("id"), "data": ""}

    extra = ''
    if context_key:
        extra = str(ctx.get(context_key, ''))

    tags = derive_tags(text, max_tags=max_tags, extra_context=extra)
    result = tags_to_string(tags)
    logger.debug(f"deriveTags: {result}")
    return {"id": action.get("id"), "data": result}
