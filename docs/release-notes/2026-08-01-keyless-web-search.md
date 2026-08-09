# 2026-08-01 — Clay can look things up

Task doc: [`docs/tasks/keyless-web-search.md`](../tasks/keyless-web-search.md)

`system/clay` could not search the web. The workflow was not the problem — the
classify → query → search → pick → read → answer chain was complete and every
gate in it was right. It was pointed at an engine nobody had credentials for,
and the one engine that needed no credentials was not a search engine.

Both are fixed, and while the reading step was open it was changed to read the
top few results instead of one.

---

## `searchWeb` now works with no credentials at all

`engine: "duckduckgo"` used to call the Instant Answer API at
`api.duckduckgo.com`. That endpoint returns a definitional abstract for
"argon2" and an empty object for almost every real question. It is not a ranked
web search, and it could not be the default behind a field named `engine`.

It now performs a real search against `html.duckduckgo.com`, parsed by a new
`_ResultsExtractor` built on the stdlib `HTMLParser`. It keys off two stable
class names, `result__a` and `result__snippet`, and ignores document structure
entirely — a layout change at DuckDuckGo costs results rather than raising.

`_unwrap_ddg_link` recovers the real destination from the `/l/?uddg=<url>`
redirect wrapper DuckDuckGo serves links in. Handing that wrapper to
`browseWeb` would fetch a redirector and extract nothing, so the URL that
leaves the search step is always the page itself. Anything that is not
http/https after unwrapping is dropped.

No scraping library was added. Clay's core dependencies are `requests` and
`dnspython`, and a search engine is not worth a third.

**The Instant Answer path is still there**, as `engine: "duckduckgo-instant"`.
It is the cheapest way to get a one-paragraph definition with a source URL. It
is simply no longer what `duckduckgo` means.

## `browseWeb` reads several pages in one action

New `urlsKey` field, modelled on `serveFileReads`' `pathsKey`: one context key
holding newline-separated URLs, one action call, each page returned as
`=== <url> ===` followed by its text, capped by `maxPages` (default 3).

A single pick had no recovery. If that one page was a JavaScript shell,
paywalled, 403, or moved, the turn had nothing and the reply had to admit the
lookup failed — with results two and three sitting right there.

- A page that fails to fetch comes back as `[error: ...]` in its own block.
  One 404 no longer ends a turn that was reading three sources.
- A URL that fails the scheme allowlist or the `_is_private_host` SSRF check
  comes back as `[refused: ...]` in its own block, and the other pages still
  return. Both checks now live in one `_refusal_for`, used by the single-URL
  and multi-URL paths alike — a second copy is how the two would come to
  disagree about what is allowed.
- On the single-URL path a refusal still returns `None`, so the id is popped
  and the workflow's default stands.
- `urlsKey` wins over `url` when both are set.
- `siteKey` is warned about and ignored alongside `urlsKey`. One `siteKey`
  names one profile file, so several pages would each overwrite it and the
  file would hold whichever was read last. The pages are still fetched and
  returned; only the saving is refused.

## `system/clay` picks up to three sources and weighs them

- `chosen_url` is now `chosen_urls` and asks for up to three, best first,
  preferring different sources — because the point of reading more than one is
  that they can disagree, and two pages from one publisher cannot. It says
  explicitly that one good URL is a fine answer, so it does not pad.
- The answering prompt now says to use the pages together: answer once and
  cite the best source when they agree; when they disagree, say so and say
  which is trusted and why — a primary source over a summary of it, a dated
  document over an undated one — and never average two answers into one that
  neither page supports. Pages that errored are to be ignored, and if none
  worked, to say the lookup did not work rather than answer from memory in a
  tone that sounds researched.
- `no-lookup.json` gained `chosen_urls`, so a turn that does not search still
  supplies every key the answering prompt interpolates.

## The training examples moved with the prompt

`url_examples` used to return one URL each. Against a prompt now asking for up
to three, that would have taught directly against the instruction — the same
lesson as the coding3 review pass, reapplied.

It is now five examples: two returning two URLs, one returning one, and two
returning `NO`. The mix is the lesson. Examples that always returned three
would teach padding, and picking a page to fill a slot is how a content farm
gets read.

A second `reply_examples` entry was added showing three fetched pages where
GOV.UK and a blog disagree and a third came back 403 — and an answer that
names the authority, says why it is trusted, and ignores the error.

`search-keys.json` is reframed as optional. Clay searches out of the box now;
that file is read only if `engine` is changed to `google`.

## Two test workflows were describing behaviour that does not exist

- `test-searchWeb.json` said missing google/bing credentials return an
  `[error: ...]` string. [The handler returns
  `None`](../../clay/actions/agent/web_actions.py#L523). Corrected, along with
  the `duckduckgo` description, and a `duckduckgo-instant` step added.
- `test-browseWeb.json`'s `autoContext` claimed to cover `siteKey` — which no
  action in the file set — and described it backwards, as *loading* a profile
  rather than writing one. Corrected, and a real `test_urls_key` step added
  covering `urlsKey` and `maxPages`.

## Tests

The six Instant-Answer tests in `TestSearchWeb` moved to `duckduckgo-instant`
rather than being deleted: the engine they describe still exists and still
behaves that way, and only the name it answers to changed.

New coverage: `TestUnwrapDdgLink`, `TestResultsExtractor`,
`TestSearchWebDuckDuckGoHtml` and `TestBrowseWebMultiPage` — including that a
snippet with no link above it is dropped rather than reattached to the previous
result, that a renamed layout yields no results instead of raising, that one
refused and one failing URL each leave the other pages intact, and that
`siteKey` writes no profile when `urlsKey` is set.

## Not fixed, and worth knowing

`_TextExtractor`, which every fetched page passes through, still keeps
navigation and cookie banners (so `maxChars` often truncates inside boilerplate
before the article starts), discards `<title>`, joins text nodes with `\n` in a
way that breaks sentences around inline `<a>`/`<em>`, and ignores the response
charset. This release changed which pages get read, not how well they are read.

## Commands

```
.venv/bin/python -m unittest clay.tests.actions.agent.test_web_actions -v
.venv/bin/python -m clay.tests
clay build
clay lint system clay
clay run system clay
```
