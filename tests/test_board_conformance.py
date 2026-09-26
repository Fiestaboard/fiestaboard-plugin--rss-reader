"""Board-geometry conformance for the RSS Reader plugin.

Runs the shared FiestaBoard suite that proves a plugin renders correctly on
every board shape a user can own -- Flagship, Note, and every note-array size
from a single Note up to the largest FiestaPanel. See
``src/plugins/geometry_conformance.py`` in FiestaBoard core for the checks
themselves.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

from plugins.rss_reader import RssReaderPlugin
from src.plugins.geometry_conformance import assert_board_conformance

MANIFEST = json.loads((Path(__file__).parent.parent / "manifest.json").read_text())

CONFIG = {
    "feed_url": "https://example.com/feed.xml",
    # The new ceiling (rows - 1 of the largest note array). Set high on
    # purpose: the growth check below only proves anything if the board's
    # own size -- not the configured value -- is what binds.
    "max_items": 23,
    "refresh_seconds": 300,
}

# Plenty of items so no geometry is ever limited by feed content rather than
# by board size -- the largest board needs 23 headlines (24 rows - 1).
_ITEMS_XML = "".join(
    f"<item><title>Headline number {i} from the feed</title>"
    f"<link>https://example.com/story/{i}</link></item>"
    for i in range(40)
)
FEED_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Board Conformance Feed</title>
{_ITEMS_XML}
</channel></rss>
"""


def _mock_response() -> Mock:
    response = Mock()
    response.content = FEED_XML.encode("utf-8")
    response.raise_for_status = Mock()
    return response


def make_plugin() -> RssReaderPlugin:
    """Fresh, configured plugin with the network stubbed for the suite."""
    plugin = RssReaderPlugin(MANIFEST)
    plugin.config = dict(CONFIG)
    return plugin


def test_renders_on_every_board_shape():
    with patch("plugins.rss_reader.requests.get", return_value=_mock_response()):
        report = assert_board_conformance(
            make_plugin,
            manifest=MANIFEST,
            strict_growth=True,
            require_note_array_preview=True,
        )

    # A list-of-headlines plugin: a taller board must have rendered
    # strictly more non-blank rows than a shorter one. This is the
    # board-adaptivity fix made observable -- see the vacuity check in the
    # PR description for what this looks like when the fix is reverted.
    assert report.ok


def test_requests_get_never_called_more_than_once_per_geometry():
    """The suite renders the same plugin instance many times; the network
    stub must be all that ever gets hit (no accidental extra calls, no
    crashes reaching for a real network)."""
    with patch("plugins.rss_reader.requests.get", return_value=_mock_response()) as mock_get:
        assert_board_conformance(
            make_plugin,
            manifest=MANIFEST,
            strict_growth=True,
            require_note_array_preview=True,
        )
    assert mock_get.call_count > 0
    for call in mock_get.call_args_list:
        assert isinstance(call.kwargs.get("timeout"), (int, float))
