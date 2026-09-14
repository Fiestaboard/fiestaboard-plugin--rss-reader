"""Tests for the rss_reader plugin."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from plugins.rss_reader import RssReaderPlugin, clean_text, format_age, parse_feed
from src.devices import BoardContext


MANIFEST = json.loads((Path(__file__).parent.parent / "manifest.json").read_text())

CONFIG = {"feed_url": "https://example.com/feed.xml", "max_items": 5, "refresh_seconds": 900}


def _rfc2822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


NOW = datetime.now(timezone.utc)

RSS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <title>Hacker News: Front Page</title>
  <link>https://news.ycombinator.com/</link>
  <item>
    <title><![CDATA[Nike exits the S&P 100 after 18 years]]></title>
    <link>https://fortune.com/nike</link>
    <pubDate>{_rfc2822(NOW - timedelta(minutes=12))}</pubDate>
  </item>
  <item>
    <title>Show HN:  Is It &lt;b&gt;Greg&lt;/b&gt;?</title>
    <link> https://isitgreg.com </link>
    <pubDate>{_rfc2822(NOW - timedelta(hours=3))}</pubDate>
  </item>
  <item>
    <title>Third item</title>
    <link>https://example.com/3</link>
  </item>
  <item><title>Fourth</title><link>https://example.com/4</link><pubDate>{_rfc2822(NOW - timedelta(days=2))}</pubDate></item>
  <item><title>Fifth</title><link>https://example.com/5</link></item>
  <item><title>Sixth</title><link>https://example.com/6</link></item>
</channel>
</rss>
"""

ATOM_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Recent Commits to FiestaBoard:main</title>
  <updated>2026-09-14T01:08:40Z</updated>
  <entry>
    <id>tag:github.com,2008:Grit::Commit/e13a3c7</id>
    <link type="application/atom+xml" rel="self" href="https://github.com/self.atom"/>
    <link type="text/html" rel="alternate" href="https://github.com/commit/e13a3c7"/>
    <title>
        docs(updating): document the beta channel (#1989)
    </title>
    <updated>{(NOW - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")}</updated>
  </entry>
  <entry>
    <id>tag:github.com,2008:Grit::Commit/abc</id>
    <link href="https://github.com/commit/abc"/>
    <title>fix: something</title>
    <published>{(NOW - timedelta(days=1)).isoformat()}</published>
  </entry>
</feed>
"""

EMPTY_RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Empty Feed</title></channel></rss>
"""


def _mock_get(content: str, status_ok: bool = True):
    response = Mock()
    response.content = content.encode("utf-8")
    if status_ok:
        response.raise_for_status = Mock()
    else:
        response.raise_for_status.side_effect = requests.HTTPError("404 Client Error")
    return Mock(return_value=response)


@pytest.fixture
def plugin():
    p = RssReaderPlugin(MANIFEST)
    p.config = dict(CONFIG)
    return p


class TestHelpers:
    def test_clean_text_strips_html_and_whitespace(self):
        assert clean_text("  Show <b>HN</b>:\n  Is &amp; It  ") == "Show HN : Is & It"

    def test_clean_text_none(self):
        assert clean_text(None) == ""

    def test_format_age_minutes(self):
        assert format_age(_rfc2822(NOW - timedelta(minutes=5)), NOW) == "5M"

    def test_format_age_hours(self):
        assert format_age((NOW - timedelta(hours=2, minutes=30)).isoformat(), NOW) == "2H"

    def test_format_age_days(self):
        assert format_age(_rfc2822(NOW - timedelta(days=3, hours=1)), NOW) == "3D"

    def test_format_age_iso_z_suffix(self):
        value = (NOW - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert format_age(value, NOW) == "45M"

    def test_format_age_naive_treated_as_utc(self):
        value = (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        assert format_age(value, NOW) == "1H"

    def test_format_age_future_clamps_to_zero(self):
        assert format_age((NOW + timedelta(hours=1)).isoformat(), NOW) == "0M"

    @pytest.mark.parametrize("value", ["", None, "yesterday", "32 Foo 2026"])
    def test_format_age_unparseable(self, value):
        assert format_age(value, NOW) == ""

    def test_parse_feed_rejects_unknown_root(self):
        with pytest.raises(ValueError):
            parse_feed(b"<html><body>nope</body></html>")


class TestRssReaderPlugin:
    def test_plugin_id(self, plugin):
        assert plugin.plugin_id == "rss_reader"

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_rss_success(self, mock_get, plugin):
        mock_get.side_effect = _mock_get(RSS_XML)

        result = plugin.fetch_data()

        assert result.available is True
        assert result.error is None
        assert result.data["feed_title"] == "Hacker News: Front Page"
        assert result.data["title"] == "Nike exits the S&P 100 after 18 years"
        assert result.data["age"] == "12M"
        assert result.data["link"] == "https://fortune.com/nike"
        assert result.data["item_count"] == 5
        assert len(result.data["items"]) == 5

        second = result.data["items"][1]
        assert second["title"] == "Show HN: Is It Greg ?"
        assert second["link"] == "https://isitgreg.com"
        assert second["age"] == "3H"
        assert result.data["items"][2]["age"] == ""
        assert result.data["items"][3]["age"] == "2D"

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_returns_all_declared_variables(self, mock_get, plugin):
        mock_get.side_effect = _mock_get(RSS_XML)

        result = plugin.fetch_data()

        for var in MANIFEST["variables"]["simple"]:
            assert var in result.data, f"'{var}' declared in manifest but missing from data"
        for arr, spec in MANIFEST["variables"]["arrays"].items():
            assert arr in result.data
            for item in result.data[arr]:
                assert set(item) == set(spec["item_fields"])
        declared = set(MANIFEST["variables"]["simple"]) | set(MANIFEST["variables"]["arrays"])
        assert set(result.data) == declared

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_atom_success(self, mock_get, plugin):
        mock_get.side_effect = _mock_get(ATOM_XML)

        result = plugin.fetch_data()

        assert result.available is True
        assert result.data["feed_title"] == "Recent Commits to FiestaBoard:main"
        assert result.data["title"] == "docs(updating): document the beta channel (#1989)"
        assert result.data["link"] == "https://github.com/commit/e13a3c7"
        assert result.data["age"] == "5H"
        assert result.data["item_count"] == 2
        assert result.data["items"][1]["link"] == "https://github.com/commit/abc"
        assert result.data["items"][1]["age"] == "1D"

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_respects_max_items(self, mock_get, plugin):
        mock_get.side_effect = _mock_get(RSS_XML)
        plugin.config = {**CONFIG, "max_items": 2}

        result = plugin.fetch_data()

        assert result.data["item_count"] == 2
        assert [i["title"] for i in result.data["items"]] == [
            "Nike exits the S&P 100 after 18 years",
            "Show HN: Is It Greg ?",
        ]

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_clamps_bad_max_items(self, mock_get, plugin):
        mock_get.side_effect = _mock_get(RSS_XML)
        plugin.config = {**CONFIG, "max_items": "lots"}

        assert plugin.fetch_data().data["item_count"] == 5

        plugin.config = {**CONFIG, "max_items": 50}
        assert plugin.fetch_data().data["item_count"] == 6

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_sends_user_agent_and_timeout(self, mock_get, plugin):
        mock_get.side_effect = _mock_get(RSS_XML)

        plugin.fetch_data()

        kwargs = mock_get.call_args.kwargs
        assert mock_get.call_args.args[0] == CONFIG["feed_url"]
        assert "FiestaBoard" in kwargs["headers"]["User-Agent"]
        assert kwargs["timeout"] == 10

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_bad_xml(self, mock_get, plugin):
        mock_get.side_effect = _mock_get("<rss><channel><title>Broken</title>")

        result = plugin.fetch_data()

        assert result.available is False
        assert "Invalid feed XML" in result.error

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_not_a_feed(self, mock_get, plugin):
        mock_get.side_effect = _mock_get("<html><body>Not a feed</body></html>")

        result = plugin.fetch_data()

        assert result.available is False
        assert "Not an RSS 2.0 or Atom feed" in result.error

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_http_error(self, mock_get, plugin):
        mock_get.side_effect = _mock_get("", status_ok=False)

        result = plugin.fetch_data()

        assert result.available is False
        assert "404" in result.error

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_network_error(self, mock_get, plugin):
        mock_get.side_effect = requests.ConnectionError("Connection refused")

        result = plugin.fetch_data()

        assert result.available is False
        assert "Connection refused" in result.error

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_empty_feed(self, mock_get, plugin):
        mock_get.side_effect = _mock_get(EMPTY_RSS_XML)

        result = plugin.fetch_data()

        assert result.available is False
        assert "no items" in result.error

    @patch("plugins.rss_reader.requests.get")
    def test_fetch_without_feed_url(self, mock_get, plugin):
        plugin.config = {}

        result = plugin.fetch_data()

        assert result.available is False
        assert "Feed URL is required" in result.error
        mock_get.assert_not_called()

    # --- validate_config ---

    def test_validate_config_ok(self, plugin):
        assert plugin.validate_config(CONFIG) == []

    def test_validate_config_missing_url(self, plugin):
        errors = plugin.validate_config({"max_items": 5})
        assert errors == ["Feed URL is required"]

    def test_validate_config_bad_scheme(self, plugin):
        errors = plugin.validate_config({"feed_url": "ftp://example.com/feed"})
        assert any("http://" in e for e in errors)

    @pytest.mark.parametrize("max_items", [0, 11, "5", 2.5, True])
    def test_validate_config_bad_max_items(self, plugin, max_items):
        errors = plugin.validate_config({**CONFIG, "max_items": max_items})
        assert any("Max items" in e for e in errors)

    def test_validate_config_refresh_below_minimum(self, plugin):
        errors = plugin.validate_config({**CONFIG, "refresh_seconds": 60})
        assert any("at least 300" in e for e in errors)

    # --- get_formatted_display ---

    @patch("plugins.rss_reader.requests.get")
    def test_get_formatted_display_shape(self, mock_get, plugin):
        mock_get.side_effect = _mock_get(RSS_XML)

        lines = plugin.get_formatted_display()

        assert lines is not None
        assert 1 <= len(lines) <= 6
        assert all(len(line) <= 22 for line in lines)
        assert lines[0] == "Hacker News: Front Pag"
        assert lines[1] == "Nike exits the S&P 100"
        assert len(lines) == 6

    @patch("plugins.rss_reader.requests.get")
    def test_get_formatted_display_uses_board_dimensions(self, mock_get, plugin):
        mock_get.side_effect = _mock_get(RSS_XML)

        with plugin._bound_board(BoardContext("note", rows=3, cols=15)):
            lines = plugin.get_formatted_display()

        assert len(lines) == 3
        assert all(len(line) <= 15 for line in lines)

    @patch("plugins.rss_reader.requests.get")
    def test_get_formatted_display_none_on_error(self, mock_get, plugin):
        mock_get.side_effect = requests.ConnectionError("down")

        assert plugin.get_formatted_display() is None


class TestManifestMetadata:
    def test_all_variables_have_descriptions_and_groups(self):
        groups = set(MANIFEST["variables"]["groups"])
        for name, meta in MANIFEST["variables"]["simple"].items():
            assert meta.get("description"), f"'{name}' missing description"
            assert meta["group"] in groups, f"'{name}' references undefined group"

    def test_array_fields_declared(self):
        items = MANIFEST["variables"]["arrays"]["items"]
        assert items["label_field"] in items["item_fields"]
