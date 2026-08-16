"""Unit and workflow-layer tests for web_actions."""

import json
import os
import tempfile
import unittest
import urllib.parse
from unittest.mock import patch, MagicMock

from ....actions.agent import web_actions
from ....lib.network_policy import NetworkResponse
from ....run import engine
from ..fixtures import make_browse_response, make_json_api_response, write_workflow, simple_workflow, temp_webactions_base


class TestBrowseWeb(unittest.TestCase):

    @staticmethod
    def _response(body, content_type='text/html; charset=utf-8'):
        return NetworkResponse(200, {'Content-Type': content_type}, body.encode())

    @patch.object(web_actions, 'request')
    def test_returns_extracted_text(self, mock_urlopen):
        mock_urlopen.return_value = self._response(
            '<html><body><p>Hello World</p></body></html>'
        )
        result = web_actions.browse_handler({"id": "out", "url": "https://example.com"}, {})
        self.assertIsNotNone(result)
        self.assertIn("Hello World", result["data"])

    def test_blocks_file_scheme(self):
        with patch('builtins.print'):
            result = web_actions.browse_handler({"id": "out", "url": "file:///etc/passwd"}, {})
        self.assertIsNone(result)

    def test_blocks_ftp_scheme(self):
        with patch('builtins.print'):
            result = web_actions.browse_handler(
                {"id": "out", "url": "ftp://files.example.com/x"}, {}
            )
        self.assertIsNone(result)

    def test_missing_url_returns_none(self):
        with patch('builtins.print'):
            result = web_actions.browse_handler({"id": "out"}, {})
        self.assertIsNone(result)

    @patch.object(web_actions, 'request')
    def test_respects_max_chars(self, mock_urlopen):
        mock_urlopen.return_value = self._response(
            '<html><body>' + ('x' * 10000) + '</body></html>'
        )
        result = web_actions.browse_handler(
            {"id": "out", "url": "https://example.com", "maxChars": 100}, {}
        )
        self.assertLessEqual(len(result["data"]), 200)

    @patch.object(web_actions, 'request')
    def test_substitutes_url_variable(self, mock_urlopen):
        mock_urlopen.return_value = self._response('<p>ok</p>')
        web_actions.browse_handler(
            {"id": "out", "url": "https://{host}/path"},
            {"host": "example.com"}
        )
        called_url = mock_urlopen.call_args.args[1]
        self.assertIn("example.com", called_url)

    @patch.object(web_actions, 'request')
    def test_error_returns_error_string(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("connection refused")
        with patch('builtins.print'):
            result = web_actions.browse_handler(
                {"id": "out", "url": "https://example.com"}, {}
            )
        self.assertIn("error", result["data"])

    @patch.object(web_actions, 'request')
    def test_json_content_type_not_html_parsed(self, mock_urlopen):
        payload = json.dumps({"key": "value"})
        mock_urlopen.return_value = self._response(payload, 'application/json')
        result = web_actions.browse_handler(
            {"id": "out", "url": "https://example.com/data"}, {}
        )
        self.assertIn("key", result["data"])
        self.assertIn("value", result["data"])

    def test_text_extractor_skips_script_style_noscript(self):
        html = (
            '<html><head><noscript><style>body{}</style></noscript></head>'
            '<body><p>visible</p></body></html>'
        )
        extractor = web_actions._TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        self.assertNotIn('body{}', text)
        self.assertIn('visible', text)


class TestListSites(unittest.TestCase):

    def test_empty_returns_empty_string(self):
        with temp_webactions_base(web_actions):
            result = web_actions.list_sites_handler({"id": "sites"}, {})
        self.assertEqual(result["data"], "")

    def test_lists_saved_profile_files(self):
        with temp_webactions_base(web_actions) as d:
            for name in ("site-a.json", "site-b.json"):
                with open(os.path.join(d, name), 'w') as f:
                    json.dump({"url": "https://example.com"}, f)
            result = web_actions.list_sites_handler({"id": "sites"}, {})
        self.assertIn("site-a.json", result["data"])
        self.assertIn("site-b.json", result["data"])


class TestLoadSite(unittest.TestCase):

    def test_missing_site_returns_empty_string(self):
        with temp_webactions_base(web_actions):
            result = web_actions.load_site_handler({"id": "site", "siteKey": "ghost"}, {})
        self.assertEqual(result["data"], "")

    def test_missing_sitekey_returns_none(self):
        with patch('builtins.print'):
            result = web_actions.load_site_handler({"id": "site"}, {})
        self.assertIsNone(result)

    def test_loads_existing_profile(self):
        with temp_webactions_base(web_actions) as d:
            path = os.path.join(d, "mysite.json")
            with open(path, 'w') as f:
                json.dump({"url": "https://mysite.com", "preview": "content here"}, f)
            result = web_actions.load_site_handler({"id": "site", "siteKey": "mysite"}, {})
        self.assertIn("mysite.com", result["data"])


class TestSearchWeb(unittest.TestCase):
    """The Instant Answer engine, which is now `duckduckgo-instant`.

    These tests moved off `duckduckgo` rather than being deleted: the engine
    they describe still exists and still behaves this way. What changed is the
    name it answers to, because `duckduckgo` is now a real web search and the
    Instant Answer API is not one — it returns an abstract for a definitional
    query and nothing at all for most others.
    """

    ENGINE = 'duckduckgo-instant'

    def _ddg_response(self, heading='Python', abstract='Python is a language.',
                      abstract_url='https://python.org', topics=None):
        payload = {
            'Heading': heading,
            'AbstractText': abstract,
            'AbstractURL': abstract_url,
            'RelatedTopics': topics or [],
        }
        return make_json_api_response(payload)

    @patch('urllib.request.urlopen')
    def test_ddg_result_stored_by_id(self, mock_urlopen):
        mock_urlopen.return_value = self._ddg_response()
        result = web_actions.search_handler(
            {"id": "hits", "query": "python", "engine": self.ENGINE}, {}
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "hits")
        self.assertIn("python.org", result["data"])

    @patch('urllib.request.urlopen')
    def test_ddg_related_topics_included(self, mock_urlopen):
        topics = [
            {"Text": "Flask web framework", "FirstURL": "https://flask.palletsprojects.com"},
            {"Text": "Django framework", "FirstURL": "https://djangoproject.com"},
        ]
        mock_urlopen.return_value = self._ddg_response(topics=topics)
        result = web_actions.search_handler(
            {"id": "hits", "query": "python frameworks", "engine": self.ENGINE}, {}
        )
        self.assertIn("Flask", result["data"])
        self.assertIn("Django", result["data"])

    @patch('urllib.request.urlopen')
    def test_ddg_nested_topic_groups_expanded(self, mock_urlopen):
        nested = [{"Topics": [
            {"Text": "Subtopic A", "FirstURL": "https://a.example.com"},
        ]}]
        mock_urlopen.return_value = self._ddg_response(abstract='', abstract_url='', topics=nested)
        result = web_actions.search_handler(
            {"id": "r", "query": "anything", "engine": self.ENGINE}, {}
        )
        self.assertIn("Subtopic A", result["data"])

    @patch('urllib.request.urlopen')
    def test_query_resolved_from_querykey(self, mock_urlopen):
        mock_urlopen.return_value = self._ddg_response()
        result = web_actions.search_handler(
            {"id": "r", "engine": self.ENGINE, "queryKey": "q"},
            {"q": "python"}
        )
        self.assertIsNotNone(result)

    @patch('urllib.request.urlopen')
    def test_query_template_substituted(self, mock_urlopen):
        mock_urlopen.return_value = self._ddg_response()
        result = web_actions.search_handler(
            {"id": "r", "engine": self.ENGINE, "query": "{topic} tutorial"},
            {"topic": "flask"}
        )
        self.assertIsNotNone(result)

    def test_missing_query_returns_none(self):
        with patch('builtins.print'):
            result = web_actions.search_handler(
                {"id": "r", "engine": "duckduckgo"}, {}
            )
        self.assertIsNone(result)

    def test_unknown_engine_returns_none(self):
        with patch('builtins.print'):
            result = web_actions.search_handler(
                {"id": "r", "engine": "yahoo", "query": "test"}, {}
            )
        self.assertIsNone(result)

    def test_google_missing_credentials_returns_none(self):
        with patch('builtins.print'):
            result = web_actions.search_handler(
                {"id": "r", "engine": "google", "query": "test"}, {}
            )
        self.assertIsNone(result)

    def test_bing_missing_apikey_returns_none(self):
        with patch('builtins.print'):
            result = web_actions.search_handler(
                {"id": "r", "engine": "bing", "query": "test"}, {}
            )
        self.assertIsNone(result)

    @patch('urllib.request.urlopen')
    def test_google_result_format(self, mock_urlopen):
        mock_urlopen.return_value = make_json_api_response({"items": [
            {"title": "Python Docs", "link": "https://docs.python.org", "snippet": "Official."},
            {"title": "PyPI", "link": "https://pypi.org", "snippet": "Packages."},
        ]})
        result = web_actions.search_handler(
            {"id": "r", "engine": "google", "query": "python", "apiKey": "k", "cx": "cx1"},
            {}
        )
        self.assertIn("Python Docs", result["data"])
        self.assertIn("docs.python.org", result["data"])

    @patch('urllib.request.urlopen')
    def test_bing_result_format(self, mock_urlopen):
        mock_urlopen.return_value = make_json_api_response({"webPages": {"value": [
            {"name": "Python.org", "url": "https://python.org", "snippet": "Welcome."},
        ]}})
        result = web_actions.search_handler(
            {"id": "r", "engine": "bing", "query": "python", "apiKey": "key123"}, {}
        )
        self.assertIn("Python.org", result["data"])

    @patch('urllib.request.urlopen', side_effect=Exception("network error"))
    def test_network_error_returns_error_string(self, _):
        result = web_actions.search_handler(
            {"id": "r", "engine": "duckduckgo", "query": "python"}, {}
        )
        self.assertIsNotNone(result)
        self.assertIn("[error:", result["data"])

    @patch('urllib.request.urlopen')
    def test_maxresults_limits_output(self, mock_urlopen):
        topics = [{"Text": f"Topic {i}", "FirstURL": f"https://t{i}.com"} for i in range(10)]
        mock_urlopen.return_value = self._ddg_response(abstract='', abstract_url='', topics=topics)
        result = web_actions.search_handler(
            {"id": "r", "engine": self.ENGINE, "query": "test", "maxResults": 3}, {}
        )
        count = sum(
            1 for line in result["data"].splitlines()
            if line and line[0].isdigit() and '. ' in line
        )
        self.assertLessEqual(count, 3)


def _serp(*results):
    """Build a DuckDuckGo HTML results page from (title, href, snippet) triples.

    Mirrors the real markup closely enough to be a real test of the parser: the
    title is an <a class="result__a"> nested in an <h2>, the href is the
    protocol-relative /l/?uddg= redirect wrapper, and the snippet is a sibling
    <a class="result__snippet"> rather than a div.
    """
    blocks = []
    for title, href, snippet in results:
        blocks.append(
            '<div class="result results_links">'
            f'<h2 class="result__title"><a class="result__a" href="{href}">{title}</a></h2>'
            f'<a class="result__snippet" href="{href}">{snippet}</a>'
            '</div>'
        )
    return '<html><body>' + ''.join(blocks) + '</body></html>'


def _wrap(url):
    """The redirect form DuckDuckGo actually serves links in."""
    return '//duckduckgo.com/l/?uddg=' + urllib.parse.quote(url, safe='') + '&rut=deadbeef'


class TestUnwrapDdgLink(unittest.TestCase):

    def test_unwraps_protocol_relative_redirect(self):
        self.assertEqual(
            web_actions._unwrap_ddg_link(_wrap('https://www.rfc-editor.org/rfc/rfc9106.html')),
            'https://www.rfc-editor.org/rfc/rfc9106.html'
        )

    def test_passes_through_a_direct_link(self):
        self.assertEqual(
            web_actions._unwrap_ddg_link('https://example.com/page'),
            'https://example.com/page'
        )

    def test_redirect_without_a_target_is_dropped(self):
        self.assertEqual(web_actions._unwrap_ddg_link('//duckduckgo.com/l/?rut=x'), '')

    def test_disallowed_scheme_is_dropped(self):
        self.assertEqual(web_actions._unwrap_ddg_link('javascript:alert(1)'), '')

    def test_empty_href_is_dropped(self):
        self.assertEqual(web_actions._unwrap_ddg_link(''), '')


class TestResultsExtractor(unittest.TestCase):

    def _parse(self, html):
        parser = web_actions._ResultsExtractor()
        parser.feed(html)
        parser.close()
        return parser.results

    def test_extracts_title_url_and_snippet(self):
        results = self._parse(_serp(
            ('RFC 9106', _wrap('https://www.rfc-editor.org/rfc/rfc9106.html'),
             'This document describes the Argon2 memory-hard function.'),
        ))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'RFC 9106')
        self.assertEqual(results[0]['url'], 'https://www.rfc-editor.org/rfc/rfc9106.html')
        self.assertIn('Argon2', results[0]['snippet'])

    def test_extracts_several_results_in_page_order(self):
        results = self._parse(_serp(
            ('First', _wrap('https://a.example.com'), 'one'),
            ('Second', _wrap('https://b.example.com'), 'two'),
            ('Third', _wrap('https://c.example.com'), 'three'),
        ))
        self.assertEqual(
            [r['url'] for r in results],
            ['https://a.example.com', 'https://b.example.com', 'https://c.example.com']
        )

    def test_snippet_without_a_link_is_dropped_not_reattached(self):
        # A stray snippet must not overwrite or attach to the result above it.
        html = (
            '<html><body>'
            '<a class="result__a" href="https://a.example.com">A</a>'
            '<div class="result__snippet">belongs to A</div>'
            '<div class="result__snippet">belongs to nothing</div>'
            '</body></html>'
        )
        results = self._parse(html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['snippet'], 'belongs to A')

    def test_result_with_unusable_href_is_skipped(self):
        results = self._parse(
            '<html><body>'
            '<a class="result__a" href="javascript:void(0)">Bad</a>'
            '<a class="result__a" href="https://ok.example.com">Good</a>'
            '</body></html>'
        )
        self.assertEqual([r['title'] for r in results], ['Good'])

    def test_unclosed_final_link_is_still_committed(self):
        # close() flushes a title left collecting, so a truncated page still
        # yields its last result rather than silently losing it.
        results = self._parse(
            '<html><body><a class="result__a" href="https://x.example.com">X'
        )
        self.assertEqual([r['url'] for r in results], ['https://x.example.com'])

    def test_layout_change_costs_results_rather_than_raising(self):
        results = self._parse('<html><body><div class="renamed"><a href="/x">y</a></div></body></html>')
        self.assertEqual(results, [])


class TestSearchWebDuckDuckGoHtml(unittest.TestCase):
    """The keyless default engine."""

    @patch('urllib.request.urlopen')
    def test_posts_the_query_to_the_html_endpoint(self, mock_urlopen):
        mock_urlopen.return_value = make_browse_response(_serp(
            ('Doc', _wrap('https://docs.example.com'), 'the docs'),
        ))
        web_actions.search_handler(
            {"id": "r", "engine": "duckduckgo", "query": "argon2id"}, {}
        )
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://html.duckduckgo.com/html/')
        self.assertIn(b'argon2id', request.data)

    @patch('urllib.request.urlopen')
    def test_results_are_formatted_with_unwrapped_urls(self, mock_urlopen):
        mock_urlopen.return_value = make_browse_response(_serp(
            ('Python Docs', _wrap('https://docs.python.org/3/'), 'Official documentation.'),
        ))
        result = web_actions.search_handler(
            {"id": "r", "engine": "duckduckgo", "query": "python docs"}, {}
        )
        self.assertIn('Python Docs', result["data"])
        self.assertIn('https://docs.python.org/3/', result["data"])
        self.assertIn('Official documentation.', result["data"])
        self.assertNotIn('uddg', result["data"])

    @patch('urllib.request.urlopen')
    def test_duplicate_urls_collapse_to_one(self, mock_urlopen):
        mock_urlopen.return_value = make_browse_response(_serp(
            ('Same', _wrap('https://dupe.example.com'), 'first'),
            ('Same again', _wrap('https://dupe.example.com'), 'second'),
            ('Other', _wrap('https://other.example.com'), 'third'),
        ))
        result = web_actions.search_handler(
            {"id": "r", "engine": "duckduckgo", "query": "x"}, {}
        )
        self.assertEqual(result["data"].count('https://dupe.example.com'), 1)
        self.assertIn('https://other.example.com', result["data"])

    @patch('urllib.request.urlopen')
    def test_maxresults_caps_the_list(self, mock_urlopen):
        mock_urlopen.return_value = make_browse_response(_serp(*[
            (f'Result {i}', _wrap(f'https://r{i}.example.com'), f'snippet {i}')
            for i in range(10)
        ]))
        result = web_actions.search_handler(
            {"id": "r", "engine": "duckduckgo", "query": "x", "maxResults": 3}, {}
        )
        self.assertIn('https://r2.example.com', result["data"])
        self.assertNotIn('https://r3.example.com', result["data"])

    @patch('urllib.request.urlopen')
    def test_no_results_is_not_an_error(self, mock_urlopen):
        mock_urlopen.return_value = make_browse_response('<html><body>nothing here</body></html>')
        result = web_actions.search_handler(
            {"id": "r", "engine": "duckduckgo", "query": "asdkjhasd"}, {}
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "r")


class TestBrowseWebMultiPage(unittest.TestCase):
    """urlsKey: several pages read in one action, each under its own heading."""

    def _page(self, body):
        html = f'<html><body><p>{body}</p></body></html>'
        return NetworkResponse(200, {'Content-Type': 'text/html; charset=utf-8'}, html.encode())

    @patch.object(web_actions, 'request')
    def test_each_url_gets_its_own_labelled_block(self, mock_urlopen):
        mock_urlopen.side_effect = [self._page('alpha'), self._page('beta')]
        result = web_actions.browse_handler(
            {"id": "pages", "urlsKey": "picked"},
            {"picked": "https://example.com/a\nhttps://claycli.org/b"}
        )
        self.assertIn('=== https://example.com/a ===', result["data"])
        self.assertIn('alpha', result["data"])
        self.assertIn('=== https://claycli.org/b ===', result["data"])
        self.assertIn('beta', result["data"])

    @patch.object(web_actions, 'request')
    def test_single_url_is_still_unlabelled(self, mock_urlopen):
        mock_urlopen.return_value = self._page('solo')
        result = web_actions.browse_handler(
            {"id": "page", "url": "https://example.com/a"}, {}
        )
        self.assertNotIn('===', result["data"])
        self.assertIn('solo', result["data"])

    @patch.object(web_actions, 'request')
    def test_maxpages_caps_how_many_are_fetched(self, mock_urlopen):
        mock_urlopen.side_effect = [self._page('one'), self._page('two')]
        domains = ['example.com', 'claycli.org']
        urls = '\n'.join(f'https://{domains[i % 2]}/r{i}' for i in range(5))
        result = web_actions.browse_handler(
            {"id": "pages", "urlsKey": "picked", "maxPages": 2}, {"picked": urls}
        )
        self.assertEqual(mock_urlopen.call_count, 2)
        self.assertNotIn('https://example.com/r2', result["data"])

    @patch.object(web_actions, 'request')
    def test_blank_lines_are_ignored(self, mock_urlopen):
        mock_urlopen.return_value = self._page('only')
        web_actions.browse_handler(
            {"id": "pages", "urlsKey": "picked"},
            {"picked": "\n  https://example.com/a  \n\n"}
        )
        self.assertEqual(mock_urlopen.call_count, 1)
        self.assertEqual(mock_urlopen.call_args.args[1], 'https://example.com/a')

    @patch.object(web_actions, 'request')
    def test_one_refused_url_does_not_lose_the_others(self, mock_urlopen):
        mock_urlopen.return_value = self._page('good page')
        with patch('builtins.print'):
            result = web_actions.browse_handler(
                {"id": "pages", "urlsKey": "picked"},
                {"picked": "file:///etc/passwd\nhttps://claycli.org/good"}
            )
        self.assertIn('[refused:', result["data"])
        self.assertIn('good page', result["data"])
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch.object(web_actions, 'request')
    def test_one_failing_fetch_does_not_lose_the_others(self, mock_urlopen):
        mock_urlopen.side_effect = [Exception("HTTP Error 403: Forbidden"), self._page('survivor')]
        with patch('builtins.print'):
            result = web_actions.browse_handler(
                {"id": "pages", "urlsKey": "picked"},
                {"picked": "https://example.com/blocked\nhttps://claycli.org/ok"}
            )
        self.assertIn('[error: HTTP Error 403: Forbidden]', result["data"])
        self.assertIn('survivor', result["data"])

    @patch.object(web_actions, 'request')
    def test_a_NO_answer_comes_back_as_a_refusal_not_a_crash(self, mock_urlopen):
        # chosen_urls replies with exactly "NO" when nothing is worth opening.
        with patch('builtins.print'):
            result = web_actions.browse_handler(
                {"id": "pages", "urlsKey": "picked"}, {"picked": "NO"}
            )
        self.assertIsNotNone(result)
        self.assertIn('[refused:', result["data"])
        self.assertEqual(mock_urlopen.call_count, 0)

    def test_empty_urlskey_returns_none(self):
        with patch('builtins.print'):
            result = web_actions.browse_handler(
                {"id": "pages", "urlsKey": "picked"}, {"picked": "   \n\n"}
            )
        self.assertIsNone(result)

    @patch.object(web_actions, 'request')
    def test_urlskey_wins_over_url_when_both_are_set(self, mock_urlopen):
        mock_urlopen.return_value = self._page('from key')
        web_actions.browse_handler(
            {"id": "pages", "url": "https://example.com/ignored", "urlsKey": "picked"},
            {"picked": "https://claycli.org/used"}
        )
        self.assertEqual(mock_urlopen.call_args.args[1], 'https://claycli.org/used')

    @patch.object(web_actions, 'request')
    def test_sitekey_is_ignored_with_urlskey_and_writes_no_profile(self, mock_urlopen):
        # One siteKey names one file; several pages would each overwrite it, so
        # the pages are still returned and nothing is saved.
        mock_urlopen.side_effect = [self._page('alpha'), self._page('beta')]
        with temp_webactions_base(web_actions) as d, patch('builtins.print'):
            result = web_actions.browse_handler(
                {"id": "pages", "urlsKey": "picked", "siteKey": "shared"},
                {"picked": "https://example.com/a\nhttps://claycli.org/b"}
            )
            written = os.listdir(d)
        self.assertEqual(written, [])
        self.assertIn('alpha', result["data"])
        self.assertIn('beta', result["data"])

    @patch.object(web_actions, 'request')
    def test_sitekey_still_saves_on_the_single_url_path(self, mock_urlopen):
        mock_urlopen.return_value = self._page('profile body')
        with temp_webactions_base(web_actions) as d:
            web_actions.browse_handler(
                {"id": "page", "url": "https://example.com/a", "siteKey": "mysite"}, {}
            )
            self.assertIn('mysite.json', os.listdir(d))


class TestBrowseWebWorkflowLayer(unittest.TestCase):

    @staticmethod
    def _response(body):
        return NetworkResponse(200, {'Content-Type': 'text/html; charset=utf-8'}, body.encode())

    @patch.object(web_actions, 'request')
    def test_result_stored_by_action_id(self, mock_urlopen):
        mock_urlopen.return_value = self._response(
            '<html><body><p>Hello from web</p></body></html>'
        )
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "page", "type": "browseWeb", "url": "https://example.com"}
            ]}))
            data = engine.run(path)
        self.assertIn("page", data)
        self.assertIn("Hello from web", data["page"])

    @patch.object(web_actions, 'request')
    def test_browse_sitekey_saves_profile_loadsite_retrieves(self, mock_urlopen):
        mock_urlopen.return_value = self._response(
            '<html><body><p>Profile content</p></body></html>'
        )
        with temp_webactions_base(web_actions) as webdir, \
             tempfile.TemporaryDirectory() as wfdir:
            path = write_workflow(wfdir, {
                "workflow": {"steps": ["browse", "load"]},
                "actionSets": {
                    "browse": [{"id": "fetched", "type": "browseWeb",
                                "url": "https://example.com", "siteKey": "example"}],
                    "load":   [{"id": "profile", "type": "loadSite", "siteKey": "example"}]
                }
            })
            data = engine.run(path)
        self.assertIn("profile", data)
        profile_data = json.loads(data["profile"])
        self.assertIn("url", profile_data)
        self.assertIn("Profile content", profile_data["preview"])

    def test_blocked_scheme_not_stored(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "danger", "type": "browseWeb", "url": "file:///etc/passwd"}
            ]}))
            with patch('builtins.print'):
                data = engine.run(path)
        self.assertNotIn("danger", data)


if __name__ == '__main__':
    unittest.main()
