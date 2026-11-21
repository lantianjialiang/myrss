import calendar
from contextlib import closing
from datetime import date, datetime, time, timedelta
from email.utils import formatdate
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import re
from secrets import compare_digest, token_urlsafe
import sqlite3
from ssl import SSLEOFError
from threading import Event, Thread
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit
from urllib.request import Request, urlopen
from xml.etree.ElementTree import Element, ParseError, SubElement, tostring

import bleach
import feedparser
from defusedxml.ElementTree import fromstring as parse_opml
from defusedxml.common import DefusedXmlException
from flask import Flask, Response, abort, redirect, render_template, request, send_file, url_for
from waitress import serve

from exports import article_export

HUB = "http://127.0.0.1:1200"
READHUB_DAILY = "/readhub/daily"
PORT = 1210
DB = Path(__file__).resolve().parents[1] / "runtime" / "reader.sqlite3"
MAX_FEED_SIZE = 8 * 1024 * 1024
SOURCE_TYPES = ("博客 / RSS", "X", "微信公众号", "YouTube", "哔哩哔哩", "微博", "小宇宙", "豆瓣", "Readhub")
app = Flask(__name__)
app.config.update(TRUSTED_HOSTS=["127.0.0.1", "localhost"], MAX_CONTENT_LENGTH=2 * 1024 * 1024)
app.jinja_env.globals["form_token"] = token_urlsafe(32)
wake = Event()


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS feeds (
                id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
                kind TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                next_check INTEGER NOT NULL DEFAULT 0, updated INTEGER, error TEXT
            );
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY, feed_id INTEGER NOT NULL REFERENCES feeds(id),
                item_key TEXT NOT NULL, title TEXT NOT NULL, link TEXT NOT NULL,
                body TEXT NOT NULL, published INTEGER, added INTEGER DEFAULT (unixepoch()),
                first_opened INTEGER, last_opened INTEGER, opens INTEGER NOT NULL DEFAULT 0,
                marked_read INTEGER NOT NULL DEFAULT 0,
                audio_url TEXT,
                UNIQUE(feed_id, item_key)
            );
            CREATE INDEX IF NOT EXISTS entries_feed ON entries(feed_id);
            CREATE INDEX IF NOT EXISTS entries_added ON entries(added);
        """)
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            columns = {column["name"] for column in conn.execute("PRAGMA table_info(entries)")}
            if "marked_read" not in columns:
                conn.execute("ALTER TABLE entries ADD COLUMN marked_read INTEGER NOT NULL DEFAULT 0")
            if "audio_url" not in columns:
                conn.execute("ALTER TABLE entries ADD COLUMN audio_url TEXT")


def web_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    return parsed._replace(fragment="").geturl()


def social_feed_url(value, kind):
    candidate = "https://" + value if re.match(r"^(?:[\w-]+\.)+[\w-]+/", value) else value
    parsed = urlsplit(candidate)
    host = parsed.hostname
    path = unquote(parsed.path).strip("/")
    if kind == "YouTube":
        youtube = host in {"youtube.com", "www.youtube.com", "m.youtube.com"}
        identifier = path.split("/", 1)[0] if youtube else value
        if re.fullmatch(r"@[\w.-]{1,100}", identifier):
            return f"{HUB}/youtube/user/{quote(identifier, safe='@')}/embed=0"
        if youtube:
            channel = re.fullmatch(r"channel/(UC[A-Za-z0-9_-]{22})(?:/.*)?", path)
            if channel:
                identifier = channel[1]
            elif path != "feeds/videos.xml":
                raise ValueError("请填写 YouTube 频道主页、@账号、频道 ID 或 RSS 地址。")
        if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", identifier):
            return f"{HUB}/youtube/channel/{identifier}/embed=0"
    else:
        if kind == "哔哩哔哩":
            known_host = host in {"space.bilibili.com", "www.bilibili.com", "bilibili.com"}
            match = re.fullmatch(r"(?:space/)?([0-9]+)(?:/.*)?", path) if known_host else None
            route, suffix = "bilibili/user/video", "/0"
            guidance = "请填写 B 站 UP 主空间链接或数字 UID。"
        else:
            known_host = host in {"weibo.com", "www.weibo.com", "weibo.cn", "m.weibo.cn"}
            match = re.fullmatch(r"(?:u/|profile/)?([0-9]+)", path) if known_host else None
            route, suffix = "weibo/user", ""
            guidance = "请填写包含数字 UID 的微博主页链接，或直接填写数字 UID。"
        identifier = match[1] if match else value
        if re.fullmatch(r"[0-9]+", identifier):
            return f"{HUB}/{route}/{identifier}{suffix}"
        if known_host:
            raise ValueError(guidance)
    return web_url(candidate)


def readhub_url(value):
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    if ((parsed.hostname in {"rsshub.app", "www.rsshub.app"} and path == READHUB_DAILY)
            or (parsed.hostname in {"readhub.cn", "www.readhub.cn"} and path == "/daily")):
        query = f"?{parsed.query}" if parsed.query else ""
        return f"{HUB}{READHUB_DAILY}{query}"
    return ""


def publication_feed_url(value, kind):
    parsed = urlsplit(value)
    path = unquote(parsed.path).strip("/")
    if kind == "小宇宙":
        if re.fullmatch(r"[0-9a-fA-F]{24}", value):
            return f"{HUB}/xiaoyuzhou/podcast/{value.lower()}"
        if parsed.hostname in {"xiaoyuzhoufm.com", "www.xiaoyuzhoufm.com"}:
            match = re.fullmatch(r"(?:podcast|episode)/([0-9a-fA-F]{24})", path)
            if match:
                return f"{HUB}/xiaoyuzhou/podcast/{match[1].lower()}"
            raise ValueError("请填写小宇宙的播客主页、单集分享链接或节目 ID。")
    elif parsed.hostname in {"douban.com", "www.douban.com", "m.douban.com"}:
        group = re.fullmatch(r"group/([A-Za-z0-9_-]+)(?:/discussion)?", path)
        if group:
            return f"{HUB}/douban/group/{group[1]}"
        doulist = re.fullmatch(r"doulist/([0-9]+)", path)
        if doulist:
            return f"{HUB}/douban/doulist/{doulist[1]}"
        person = re.fullmatch(r"people/([0-9]+)(?:/status)?", path)
        if person:
            return f"{HUB}/douban/people/{person[1]}/status"
        raise ValueError("请填写豆瓣小组、豆列或带数字 ID 的个人主页，也可粘贴 RSSHub 路由。")
    return web_url(value)


def normalize(value, kind):
    if len(value) > 2048 or any(char.isspace() for char in value):
        raise ValueError("请输入单个有效的链接或账号。")
    if value.startswith("rsshub://"):
        return HUB + "/" + value.removeprefix("rsshub://").lstrip("/")
    if value.startswith("/") and not value.startswith("//"):
        return HUB + value
    if local_readhub := readhub_url(value):
        return local_readhub
    if kind in {"小宇宙", "豆瓣"}:
        url = publication_feed_url(value, kind)
        if not url:
            raise ValueError("请填写该平台的节目、小组、个人主页或 RSS 地址。")
        return url
    if kind in {"YouTube", "哔哩哔哩", "微博"}:
        url = social_feed_url(value, kind)
        if not url:
            raise ValueError("请填写该平台的账号、个人主页或 RSS 地址。")
        return url
    if kind == "X":
        if not value.startswith(("http://", "https://")) and "/" in value:
            value = "https://" + value
        parsed = urlsplit(value)
        if parsed.hostname in ("x.com", "www.x.com", "twitter.com", "www.twitter.com"):
            value = parsed.path.strip("/")
        handle = value.removeprefix("@")
        if re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
            return f"{HUB}/twitter/user/{handle.lower()}"
    if kind == "微信公众号":
        parsed = urlsplit(value)
        if parsed.hostname == "mp.weixin.qq.com" and parsed.path == "/mp/homepage":
            params = parse_qs(parsed.query)
            biz, hid = params.get("__biz", [""])[0], params.get("hid", [""])[0]
            cid = params.get("cid", [""])[0]
            if re.fullmatch(r"[A-Za-z0-9_+=-]+", biz) and hid.isdecimal() and (not cid or cid.isdecimal()):
                return f"{HUB}/wechat/mp/homepage/{biz}/{hid}" + (f"/{cid}" if cid else "")
        if parsed.hostname == "mp.weixin.qq.com":
            raise ValueError("请填公众号的 RSS 地址、Wechat2RSS 订阅 ID，或带有 /mp/homepage 的栏目链接。")
        if re.fullmatch(r"[a-fA-F0-9]{40}", value):
            return f"{HUB}/wechat/wechat2rss/{value.lower()}"
    url = web_url(value)
    if not url:
        raise ValueError("请填 http(s) 链接、rsshub:// 地址或有效的账号。")
    return url


class FeedLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and "alternate" in (attrs.get("rel") or "").lower().split():
            if attrs.get("type") in ("application/rss+xml", "application/atom+xml") and attrs.get("href"):
                self.hrefs.append(attrs["href"])


def download(url):
    req = Request(url, headers={"User-Agent": "LocalRSSReader/1.0", "Accept": "application/atom+xml, application/rss+xml, application/xml, text/html;q=0.8, */*;q=0.5"})
    for attempt in range(2):
        try:
            with urlopen(req, timeout=45 if url.startswith(HUB + "/") else 14) as response:
                body = response.read(MAX_FEED_SIZE + 1)
                if len(body) > MAX_FEED_SIZE:
                    raise ValueError("订阅源超过 8 MB。")
                return response.geturl(), response.headers.get("Content-Type", ""), body
        except (SSLEOFError, URLError) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            if not isinstance(reason, SSLEOFError):
                raise
            if attempt:
                raise ValueError("订阅源的 HTTPS 连接中断，重试后仍未成功。稍后会自动刷新。") from exc


def fetch_feed(url):
    final_url, content_type, body = download(readhub_url(url) or url)
    if "text/html" in content_type.lower():
        links = FeedLinks()
        links.feed(body.decode("utf-8", errors="replace"))
        for href in links.hrefs:
            candidate = web_url(urljoin(final_url, href))
            if candidate:
                final_url, content_type, body = download(candidate)
                break
    feed = feedparser.parse(body, response_headers={"content-location": final_url, "content-type": content_type})
    if not feed.version or (feed.bozo and not feed.entries):
        raise ValueError("未找到可读取的 RSS 或 Atom。请检查订阅地址。")
    return feed


def entry_values(entry):
    title = entry.get("title") or "无标题"
    link = web_url(entry.get("link", ""))
    body = next((item.value for item in entry.get("content", []) if item.get("value")), entry.get("summary", ""))
    if not isinstance(body, str):
        body = ""
    body = bleach.clean(
        body,
        tags={"p", "br", "div", "span", "h1", "h2", "h3", "h4", "strong", "em", "b", "i", "s",
              "blockquote", "pre", "code", "ul", "ol", "li", "a", "img", "hr", "figure", "figcaption",
              "table", "thead", "tbody", "tr", "th", "td"},
        attributes={"a": ["href", "title"], "img": ["src", "alt", "title"]},
        protocols={"http", "https"},
        strip=True,
    )
    key = entry.get("id") or link or sha256((title + body).encode()).hexdigest()
    date = entry.get("published_parsed") or entry.get("updated_parsed")
    audio_url = next((web_url(item["href"]) for item in entry.get("enclosures", [])
                      if item.get("type", "").lower().startswith("audio/") and item.get("href")), "")
    return key, title, link, body, calendar.timegm(date) if date else None, audio_url or None


def refresh(source):
    try:
        feed = fetch_feed(source["url"])
        items = [entry_values(entry) for entry in feed.entries]
    except HTTPError as exc:
        error = f"获取失败（HTTP {exc.code}）。"
        if source["url"].startswith(HUB + "/twitter/"):
            error += "请检查 RSSHub 的 X 凭据和网络。"
        if source["url"].startswith(HUB + "/douban/people/"):
            error += "请检查数字用户 ID。需要登录才能看到的广播可能需要配置 DOUBAN_COOKIE。"
    except (OSError, ValueError) as exc:
        error = str(exc)[:250]
    else:
        with closing(connect()) as conn, conn:
            conn.executemany("""
                INSERT INTO entries (feed_id, item_key, title, link, body, published, audio_url) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feed_id, item_key) DO UPDATE SET title=excluded.title, link=excluded.link,
                    body=excluded.body, published=coalesce(excluded.published, entries.published),
                    audio_url=coalesce(excluded.audio_url, entries.audio_url)
            """, [(source["id"], *item) for item in items])
            conn.execute("""UPDATE feeds SET title=?, updated=unixepoch(), error=NULL,
                            next_check=unixepoch()+1800 WHERE id=?""",
                         (feed.feed.get("title") or source["title"], source["id"]))
        return
    with closing(connect()) as conn, conn:
        conn.execute("UPDATE feeds SET error=?, next_check=unixepoch()+900 WHERE id=?", (error, source["id"]))


def refresh_loop():
    while True:
        wake.clear()
        with closing(connect()) as conn:
            sources = conn.execute("SELECT * FROM feeds WHERE active=1 AND next_check<=unixepoch() ORDER BY next_check, id").fetchall()
        for source in sources:
            try:
                refresh(source)
            except Exception:
                app.logger.exception("Could not refresh source %s", source["id"])
                with closing(connect()) as conn, conn:
                    conn.execute("UPDATE feeds SET error=?, next_check=unixepoch()+900 WHERE id=?",
                                 ("解析失败，详见阅读器日志。", source["id"]))
        wake.wait(20)


@app.before_request
def protect_local_actions():
    if request.method == "POST":
        submitted = request.form.get("form_token", "").encode()
        expected = app.jinja_env.globals["form_token"].encode()
        if not compare_digest(submitted, expected):
            return render_template("message.html", title="表单已失效",
                                   message="请返回订阅页面，重新提交表单。"), 403


@app.after_request
def browser_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; "
        "img-src http: https:; media-src http: https:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.template_filter()
def localtime(value):
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M") if value else ""


@app.get("/")
def index():
    selected = request.args.get("feed", type=int)
    view = request.args.get("view", "all")
    if view not in {"all", "unread", "archive"}:
        abort(400)
    archive = view == "archive"
    day = request.args.get("day", "") if archive else ""
    start = end = None
    if day:
        try:
            selected_day = date.fromisoformat(day)
            day = selected_day.isoformat()
            start = int(datetime.combine(selected_day, time.min).timestamp())
            end = int(datetime.combine(selected_day + timedelta(days=1), time.min).timestamp())
        except (OSError, OverflowError, ValueError):
            abort(400)
    page = max(1, min(request.args.get("page", 1, type=int), 1_000_000))
    with closing(connect()) as conn:
        feeds = conn.execute("""
            SELECT f.*, count(e.id) FILTER (WHERE e.first_opened IS NULL AND e.marked_read=0) AS unread,
                count(e.id) AS total
            FROM feeds f LEFT JOIN entries e ON f.id=e.feed_id
            WHERE f.active=1 OR ?=1 GROUP BY f.id ORDER BY f.kind, f.title
        """, (archive,)).fetchall()
        entries = conn.execute("""
            SELECT e.id, e.feed_id, e.title, e.published, e.added, f.title AS source,
                (e.first_opened IS NULL AND e.marked_read=0) AS unread
            FROM entries e JOIN feeds f ON f.id=e.feed_id
            WHERE (f.active=1 OR ?=1) AND (? IS NULL OR f.id=?)
                AND (?=0 OR (e.first_opened IS NULL AND e.marked_read=0))
                AND (? IS NULL OR (e.added>=? AND e.added<?))
            ORDER BY CASE WHEN ?=1 THEN e.added ELSE coalesce(e.published, e.added) END DESC, e.id DESC
            LIMIT 41 OFFSET ?
        """, (archive, selected, selected, view == "unread", start, start, end, archive, (page - 1) * 40)).fetchall()
    return render_template("index.html", feeds=feeds, entries=entries[:40], selected=selected, source_types=SOURCE_TYPES,
                           view=view, archive=archive, day=day, page=page, more=len(entries) > 40)


@app.get("/healthz")
def health():
    return "ok"


@app.get("/feed.xml")
def combined_feed():
    with closing(connect()) as conn:
        entries = conn.execute("""
            SELECT e.*, f.title AS source FROM entries e JOIN feeds f ON f.id=e.feed_id
            WHERE f.active=1 ORDER BY coalesce(e.published, e.added) DESC, e.id DESC LIMIT 100
        """).fetchall()
    root = Element("rss", version="2.0")
    channel = SubElement(root, "channel")
    SubElement(channel, "title").text = "我的 RSS"
    SubElement(channel, "link").text = url_for("index", _external=True)
    SubElement(channel, "description").text = "本机订阅源的最近 100 篇文章"
    for entry in entries:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = entry["title"]
        SubElement(item, "guid", isPermaLink="false").text = f"local-rss:{entry['id']}"
        SubElement(item, "link").text = entry["link"] or url_for("article", entry_id=entry["id"], _external=True)
        SubElement(item, "category").text = entry["source"]
        SubElement(item, "description").text = entry["body"]
        if entry["published"]:
            SubElement(item, "pubDate").text = formatdate(entry["published"], usegmt=True)
    return Response(tostring(root, encoding="utf-8", xml_declaration=True), mimetype="application/rss+xml")


@app.get("/library")
def library():
    with closing(connect()) as conn:
        feeds = conn.execute("""
            SELECT f.id, f.title, f.active, count(e.id) AS total
            FROM feeds f LEFT JOIN entries e ON e.feed_id=f.id GROUP BY f.id ORDER BY f.title
        """).fetchall()
    return render_template("library.html", feeds=feeds, selected=request.args.get("feed", type=int))


@app.get("/library/articles")
def export_articles():
    source_id = request.args.get("feed", type=int)
    file_format = request.args.get("format", "md")
    mode = request.args.get("mode", "single")
    if file_format not in {"pdf", "md"} or mode not in {"single", "multiple"}:
        abort(400)
    with closing(connect()) as conn:
        source = conn.execute("SELECT title FROM feeds WHERE id=?", (source_id,)).fetchone() if source_id else None
        if source_id and not source:
            abort(404)
        entries = conn.execute("""
            SELECT e.*, f.title AS source FROM entries e JOIN feeds f ON f.id=e.feed_id
            WHERE (? IS NULL OR f.id=?)
            ORDER BY f.title, coalesce(e.published, e.added) DESC, e.id DESC
        """, (source_id, source_id)).fetchall()
    if not entries:
        return render_template("message.html", title="暂无可导出的文章",
                               message="所选订阅还没有同步过文章。"), 400
    title = source["title"] if source else "全部订阅归档"
    base = f"myrss-feed-{source_id}" if source else "myrss-archive"
    multiple = mode == "multiple"
    extension = "zip" if multiple else file_format
    return send_file(article_export(title, entries, file_format, multiple), as_attachment=True,
                     download_name=f"{base}.{extension}",
                     mimetype={"zip": "application/zip", "pdf": "application/pdf", "md": "text/markdown"}[extension])


@app.get("/library/subscriptions")
def export_subscriptions():
    with closing(connect()) as conn:
        feeds = conn.execute("SELECT url, title, kind FROM feeds WHERE active=1 ORDER BY kind, title").fetchall()
    root = Element("opml", version="2.0")
    SubElement(SubElement(root, "head"), "title").text = "我的 RSS"
    body = SubElement(root, "body")
    for feed in feeds:
        SubElement(body, "outline", type="rss", text=feed["title"], title=feed["title"],
                   xmlUrl=feed["url"], myrssKind=feed["kind"])
    content = tostring(root, encoding="utf-8", xml_declaration=True)
    return send_file(BytesIO(content), as_attachment=True, download_name="myrss-subscriptions.opml",
                     mimetype="text/x-opml")


@app.post("/library/subscriptions")
def import_subscriptions():
    upload = request.files.get("opml")
    if not upload:
        abort(400)
    try:
        root = parse_opml(upload.read())
        if root.tag != "opml":
            raise ValueError("Not OPML")
    except (ParseError, DefusedXmlException, ValueError):
        return render_template("message.html", title="导入失败", message="请选择有效的 OPML 订阅文件。"), 400
    valid, skipped = {}, 0
    for outline in root.iter("outline"):
        url = outline.get("xmlUrl", "").strip()
        if not url:
            continue
        kind = outline.get("myrssKind", "")
        if kind not in SOURCE_TYPES:
            kind = "博客 / RSS"
        try:
            normalized = normalize(url, kind)
        except ValueError:
            skipped += 1
            continue
        title = (outline.get("title") or outline.get("text") or normalized)[:2048]
        valid.setdefault(normalized, (title, kind))
    if not valid:
        return render_template("message.html", title="没有可导入的订阅", message="文件中没有有效的订阅地址。"), 400
    with closing(connect()) as conn, conn:
        conn.executemany("""
            INSERT INTO feeds(url, title, kind) VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET active=1, next_check=0 WHERE feeds.active=0
        """, [(url, title, kind) for url, (title, kind) in valid.items()])
    wake.set()
    return render_template("message.html", title="导入完成",
                           message=f"已合并 {len(valid)} 个订阅地址，跳过 {skipped} 个无效地址。")


@app.post("/feeds")
def add_feed():
    kind = request.form.get("kind", "博客 / RSS")
    if kind not in SOURCE_TYPES:
        abort(400)
    try:
        url = normalize(request.form.get("url", "").strip(), kind)
    except ValueError as exc:
        return render_template("message.html", title="添加订阅失败", message=str(exc)), 400
    if kind == "博客 / RSS" and urlsplit(url)._replace(query="", fragment="").geturl() == HUB + READHUB_DAILY:
        kind = "Readhub"
    with closing(connect()) as conn, conn:
        row = conn.execute("""
            INSERT INTO feeds(url, title, kind) VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET active=1, next_check=0, kind=excluded.kind RETURNING id
        """, (url, url, kind)).fetchone()
    wake.set()
    return redirect(url_for("index", feed=row["id"]), code=303)


@app.post("/refresh")
def refresh_now():
    selected = request.form.get("feed", type=int)
    with closing(connect()) as conn, conn:
        conn.execute("UPDATE feeds SET next_check=0 WHERE active=1 AND (? IS NULL OR id=?)", (selected, selected))
    wake.set()
    return redirect(url_for("index", feed=selected), code=303)


@app.post("/feeds/<int:feed_id>/pause")
def pause(feed_id):
    with closing(connect()) as conn, conn:
        conn.execute("UPDATE feeds SET active=0 WHERE id=?", (feed_id,))
    return redirect(url_for("index"), code=303)


@app.post("/read-all")
def mark_all_read():
    source_id = request.form.get("feed", type=int)
    view = request.form.get("view", "all")
    if ("feed" in request.form and source_id is None) or view not in {"all", "unread"}:
        abort(400)
    with closing(connect()) as conn, conn:
        conn.execute("""
            UPDATE entries SET marked_read=1
            WHERE marked_read=0 AND first_opened IS NULL AND feed_id IN (
                SELECT id FROM feeds WHERE active=1 AND (? IS NULL OR id=?)
            )
        """, (source_id, source_id))
    return redirect(url_for("index", feed=source_id, view=view), code=303)


@app.post("/articles/<int:entry_id>/open")
def open_article(entry_id):
    with closing(connect()) as conn, conn:
        updated = conn.execute("""
            UPDATE entries SET first_opened=coalesce(first_opened, unixepoch()),
                last_opened=unixepoch(), opens=opens+1 WHERE id=?
        """, (entry_id,))
        if not updated.rowcount:
            abort(404)
    if request.args.get("inline") == "1":
        return render_template("article_body.html", entry=get_entry(entry_id))
    return redirect(url_for("article", entry_id=entry_id), code=303)


def get_entry(entry_id):
    with closing(connect()) as conn:
        entry = conn.execute("""
            SELECT e.*, f.title AS source, f.kind FROM entries e JOIN feeds f ON f.id=e.feed_id WHERE e.id=?
        """, (entry_id,)).fetchone()
    if not entry:
        abort(404)
    return entry


@app.get("/articles/<int:entry_id>")
def article(entry_id):
    return render_template("article.html", entry=get_entry(entry_id))


@app.get("/stats")
def stats():
    with closing(connect()) as conn:
        sources = conn.execute("""
            SELECT f.title, f.kind, f.active,
                count(e.id) FILTER (WHERE e.last_opened>=unixepoch()-30*86400) AS recent,
                count(e.first_opened) AS total, coalesce(sum(e.opens), 0) AS opens
            FROM feeds f LEFT JOIN entries e ON e.feed_id=f.id
            GROUP BY f.id HAVING f.active=1 OR total>0 ORDER BY recent DESC, total DESC, f.title
        """).fetchall()
    return render_template("stats.html", sources=sources, total=sum(source["recent"] for source in sources))


if __name__ == "__main__":
    initialize()
    Thread(target=refresh_loop, daemon=True).start()
    serve(app, host="127.0.0.1", port=PORT)
