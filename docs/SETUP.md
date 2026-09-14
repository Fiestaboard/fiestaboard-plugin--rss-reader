# RSS Reader Setup

Show the latest headlines from any RSS or Atom feed on your board.

## Overview

**What it does:**
- Fetches one RSS 2.0 or Atom feed URL
- Exposes the newest items (title, age, link) as template variables
- Strips HTML from titles so they display cleanly on the board
- No API key required

**Prerequisites:**
- ✅ Internet connection (to reach the feed host)
- ✅ A public feed URL (see "Finding a Feed URL" below)

## Quick Setup

### 1. Enable the Plugin

In the FiestaBoard web UI, go to **Integrations**, find **RSS Reader**, and click **Enable**.

Or add to your `.env` file:
```bash
RSS_READER_ENABLED=true
```

### 2. Configure

Click **Configure** and fill in:

- **Feed URL** — The RSS or Atom feed to read, e.g. `https://hnrss.org/frontpage`
- **Max Items** — How many of the newest items to expose (1–10, default 5)
- **Refresh Interval** — How often to re-fetch the feed in seconds (default 900 = 15 minutes, minimum 300)

### 3. Add a Template

Go to **Pages** and create a page. A simple news ticker:

```
{{rss_reader.feed_title}}
{{rss_reader.items.0.title}}
{{rss_reader.items.1.title}}
{{rss_reader.items.2.title}}
{{rss_reader.items.3.title}}
{{rss_reader.items.4.title}}
```

Titles longer than the board width are cut off at the right edge. To see how old each item is,
add the age to a line:

```
{{rss_reader.items.0.title}} {{rss_reader.items.0.age}}
```

---

## Finding a Feed URL

Most news sites, blogs and services publish a feed. Look for:

- An orange RSS icon or a link labelled "RSS", "Feed", "Subscribe" or "Atom"
- URLs ending in `/feed`, `/rss`, `/rss.xml`, `/atom.xml` or `.atom`
- Aggregators such as [hnrss.org](https://hnrss.org/) (Hacker News), Reddit (`https://www.reddit.com/r/<subreddit>/.rss`), GitHub (`https://github.com/<owner>/<repo>/commits/main.atom`)

Paste the URL into a browser first — you should see XML starting with `<rss` or `<feed`.

---

## Template Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `{{feed_title}}` | Feed title | `Hacker News: Front Page` |
| `{{title}}` | Newest item title | `Show HN: Is It Greg?` |
| `{{age}}` | Newest item age (`M` minutes, `H` hours, `D` days) | `12M` |
| `{{link}}` | Newest item URL | `https://...` |
| `{{item_count}}` | Number of items exposed | `5` |
| `{{items.N.title}}` | Nth item title (0-based, up to `max_items - 1`) | `Rust 2.0 released` |
| `{{items.N.age}}` | Nth item age | `2H` |
| `{{items.N.link}}` | Nth item URL | `https://...` |

`age` is empty when the feed does not include a parseable date for that item.

## Configuration Reference

| Setting | Type | Required | Default | Description |
|---------|------|----------|---------|-------------|
| `enabled` | boolean | No | `false` | Enable or disable the plugin |
| `feed_url` | string | Yes | — | RSS 2.0 or Atom feed URL (`http://` or `https://`) |
| `max_items` | integer | No | `5` | Newest items to expose (1–10) |
| `refresh_seconds` | integer | No | `900` | Re-fetch interval in seconds (300–86400) |

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RSS_READER_ENABLED` | No | `false` | Enable RSS reader feature |

## Display Example

```
 HACKER NEWS
SHOW HN: IS IT GREG 5M
NIKE EXITS S&P 100 12M
RUST 2.0 RELEASED   1H
SPACEX LANDS ON MAR 2H
PYTHON 4 ANNOUNCED  3H
```

---

## Troubleshooting

**"Feed URL is required"**
- Make sure the Feed URL field is not empty and starts with `http://` or `https://`

**"Invalid feed XML" / "Not an RSS 2.0 or Atom feed"**
- Open the URL in a browser; it must return XML starting with `<rss` or `<feed`
- Some sites return an HTML page (or a login page) instead of the feed — use the direct feed link
- RSS 1.0 (RDF) feeds are not supported

**"Feed contains no items"**
- The feed parsed correctly but has no `<item>` / `<entry>` elements

**Headlines are stale**
- The feed is re-fetched every **Refresh Interval** seconds (default 15 minutes)
- The `age` values are computed at fetch time, so they can lag by up to one refresh interval

**Plugin shows "Not Available"**
- Check that the feed host is reachable and your network allows outbound HTTPS
- Check logs: `docker-compose logs | grep -i rss`
