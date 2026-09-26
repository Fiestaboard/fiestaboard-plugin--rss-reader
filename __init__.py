"""RSS Reader plugin for FiestaBoard.

Fetches a single RSS 2.0 or Atom feed and exposes its newest items.
"""

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.devices import DEVICE_DIMENSIONS, MAX_NOTES_PER_AXIS, NOTE_ROWS
from src.plugins.base import PluginBase, PluginResult

logger = logging.getLogger(__name__)

USER_AGENT = "FiestaBoard (https://github.com/FiestaBoard/FiestaBoard)"
ATOM_NS = "{http://www.w3.org/2005/Atom}"

DEFAULT_MAX_ITEMS = 5

# The most headlines any board could ever have room for: a full 8x8 note
# array (the largest FiestaPanel) minus the one row this plugin always
# spends on the feed title. Derived from the platform's own geometry limits
# rather than an arbitrary literal, so it never falls behind board.rows the
# way the old fixed cap of 10 did (a 24-row panel needs 23 headlines and
# could only ever get 10).
MAX_ITEMS_CEILING = MAX_NOTES_PER_AXIS * NOTE_ROWS - 1

# Honesty bounds for manifest.json's max_lengths (measured in tiles). Kept in
# sync with the "feed_title", "title" and "items.*.link" declarations there.
FEED_TITLE_MAX_LENGTH = 22
TITLE_MAX_LENGTH = 66
LINK_MAX_LENGTH = 200

_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(text: Optional[str]) -> str:
    """Strip HTML tags, unescape entities and collapse whitespace."""
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    return " ".join(text.split())


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 or RFC 2822 date string into an aware datetime."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_age(published: Optional[str], now: Optional[datetime] = None) -> str:
    """Return a short relative age like "5M", "2H" or "3D"; "" if unparseable."""
    dt = _parse_date(published)
    if dt is None:
        return ""
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - dt).total_seconds()))
    if seconds < 3600:
        return f"{seconds // 60}M"
    if seconds < 86400:
        return f"{seconds // 3600}H"
    return f"{seconds // 86400}D"


def parse_feed(xml_bytes: bytes) -> Tuple[str, List[Dict[str, str]]]:
    """Parse RSS 2.0 or Atom XML into (feed_title, items).

    Each item is {"title", "link", "published"}; items keep feed order.
    Raises ET.ParseError on bad XML and ValueError on an unknown format.
    """
    root = ET.fromstring(xml_bytes)
    items: List[Dict[str, str]] = []

    if root.tag == f"{ATOM_NS}feed":
        feed_title = clean_text(root.findtext(f"{ATOM_NS}title"))
        for entry in root.findall(f"{ATOM_NS}entry"):
            link = ""
            for link_el in entry.findall(f"{ATOM_NS}link"):
                if link_el.get("rel", "alternate") == "alternate":
                    link = link_el.get("href", "")
                    break
            items.append({
                "title": clean_text(entry.findtext(f"{ATOM_NS}title")),
                "link": link.strip(),
                "published": (
                    entry.findtext(f"{ATOM_NS}updated")
                    or entry.findtext(f"{ATOM_NS}published")
                    or ""
                ),
            })
        return feed_title, items

    channel = root.find("channel")
    if channel is None:
        raise ValueError("Not an RSS 2.0 or Atom feed")

    feed_title = clean_text(channel.findtext("title"))
    for item in channel.findall("item"):
        items.append({
            "title": clean_text(item.findtext("title")),
            "link": (item.findtext("link") or "").strip(),
            "published": item.findtext("pubDate") or "",
        })
    return feed_title, items


class RssReaderPlugin(PluginBase):
    """RSS Reader plugin.

    Fetches one RSS/Atom feed URL and exposes the newest items as
    template variables.
    """

    @property
    def plugin_id(self) -> str:
        return "rss_reader"

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate feed URL and item count."""
        errors = []

        feed_url = (config.get("feed_url") or "").strip()
        if not feed_url:
            errors.append("Feed URL is required")
        elif not feed_url.startswith(("http://", "https://")):
            errors.append("Feed URL must start with http:// or https://")

        max_items = config.get("max_items", DEFAULT_MAX_ITEMS)
        if (
            not isinstance(max_items, int)
            or isinstance(max_items, bool)
            or not 1 <= max_items <= MAX_ITEMS_CEILING
        ):
            errors.append(f"Max items must be a whole number between 1 and {MAX_ITEMS_CEILING}")

        errors.extend(self._validate_refresh_seconds(config))
        return errors

    def fetch_data(self) -> PluginResult:
        """Fetch and parse the configured feed."""
        feed_url = (self.config.get("feed_url") or "").strip()
        if not feed_url:
            return PluginResult(available=False, error="Feed URL is required")

        try:
            response = requests.get(
                feed_url,
                headers={"User-Agent": USER_AGENT},
                timeout=10,
            )
            response.raise_for_status()

            feed_title, items = parse_feed(response.content)
            # Truncate to the manifest's declared max_length so a long feed
            # title can never violate the honesty contract page templates
            # rely on for sizing.
            feed_title = feed_title[:FEED_TITLE_MAX_LENGTH]

            max_items = self.config.get("max_items", DEFAULT_MAX_ITEMS)
            if not isinstance(max_items, int) or isinstance(max_items, bool):
                max_items = DEFAULT_MAX_ITEMS

            # self.board is None outside a board-scoped render (legacy
            # callers, unit tests); assume a Flagship rather than crash.
            board = self.board
            board_rows = board.rows if board else DEVICE_DIMENSIONS["flagship"].rows
            board_cols = board.cols if board else DEVICE_DIMENSIONS["flagship"].cols

            # One row is always spent on the feed title, so a board can show
            # at most rows - 1 headlines. The configured max_items and the
            # platform-wide ceiling are both upper bounds too, so whichever
            # is smallest wins -- the point is that the board's own size can
            # never be the thing capping this below what the user asked for.
            board_cap = max(1, board_rows - 1)
            effective_cap = max(1, min(MAX_ITEMS_CEILING, max_items, board_cap))
            items = items[:effective_cap]

            if not items:
                return PluginResult(available=False, error="Feed contains no items")

            now = datetime.now(timezone.utc)
            for item in items:
                item["age"] = format_age(item.pop("published"), now)
                # Same honesty guarantee as feed_title above: RSS headlines
                # and links are arbitrary-length third-party text.
                item["title"] = item["title"][:TITLE_MAX_LENGTH]
                item["link"] = item["link"][:LINK_MAX_LENGTH]

            newest = items[0]
            formatted_lines = [feed_title[:board_cols]] + [item["title"][:board_cols] for item in items]

            return PluginResult(
                available=True,
                data={
                    "feed_title": feed_title,
                    "title": newest["title"],
                    "age": newest["age"],
                    "link": newest["link"],
                    "item_count": len(items),
                    "items": items,
                },
                formatted_lines=formatted_lines,
            )

        except ET.ParseError as e:
            logger.warning("Invalid feed XML from %s: %s", feed_url, e)
            return PluginResult(available=False, error=f"Invalid feed XML: {e}")
        except Exception as e:
            logger.exception("Error fetching RSS feed")
            return PluginResult(available=False, error=str(e))

    def get_formatted_display(self) -> Optional[List[str]]:
        """Feed title on line 1, then one item title per remaining line."""
        # Pass self.board through explicitly: get_data(None) would rebind
        # self.board to None for the duration of the underlying fetch_data()
        # call, which would fetch a Flagship-sized item count no matter how
        # big the board actually bound here is.
        result = self.get_data(self.board)
        if not result.available or not result.data:
            return None

        rows = self.board.rows if self.board else 6
        cols = self.board.cols if self.board else 22

        lines = [result.data["feed_title"][:cols]]
        for item in result.data["items"][: rows - 1]:
            lines.append(item["title"][:cols])
        return lines


# Export the plugin class
Plugin = RssReaderPlugin
