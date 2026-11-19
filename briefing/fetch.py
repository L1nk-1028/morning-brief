"""抓取并解析 RSS / Atom 新闻源。

这个模块只依赖 Python 标准库，目的是让项目在本地和 GitHub Actions 上
都能直接运行，不需要安装任何第三方包。
"""

from __future__ import annotations

import gzip
import html
import re
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Iterable

BEIJING = timezone(timedelta(hours=8))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 MorningBrief/1.0"
)

_NAMED_ENTITY = re.compile(r"&([a-zA-Z][a-zA-Z0-9]+);")
_BARE_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_XML_DECL_ENCODING = re.compile(r"encoding=[\"']([^\"']+)[\"']", re.I)
_META_CHARSET = re.compile(r"charset=([\w-]+)", re.I)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class Article:
    title: str
    url: str
    summary: str
    source_id: str
    source_name: str
    section: str
    lang: str
    weight: float = 1.0
    published: datetime | None = None
    score: float = 0.0
    top_score: float = 0.0
    title_zh: str = ""
    summary_zh: str = ""
    why: str = ""
    uid: str = ""

    @property
    def display_title(self) -> str:
        return self.title_zh or self.title

    @property
    def display_summary(self) -> str:
        return self.summary_zh or self.summary


@dataclass
class FetchResult:
    articles: list[Article] = field(default_factory=list)
    ok_sources: int = 0
    failed_sources: int = 0
    errors: list[str] = field(default_factory=list)
    total_items: int = 0


class _TextExtractor(HTMLParser):
    """把 HTML 片段转成纯文本，忽略脚本和样式。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() in {"script", "style"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return " ".join(self.parts)


def _local(tag: str) -> str:
    """去掉 XML 命名空间，只保留小写标签名。"""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def clean_text(value: str | None, limit: int = 240) -> str:
    """清理 RSS 里的 HTML、实体和多余空白，并截断到适合早报的长度。"""
    if not value:
        return ""
    raw = _CONTROL_CHARS.sub("", str(value)).strip()
    if not raw:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        text = parser.text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(阅读全文|查看全文|原文链接)[:：\s]*", "", text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("。", "！", "？", ". ", "! ", "? "):
        pos = cut.rfind(sep)
        if pos >= int(limit * 0.55):
            return cut[: pos + len(sep)].strip()
    return cut.rstrip("，,；;：: ") + "…"


def _decode(data: bytes, content_type: str = "") -> str:
    """按 Content-Type、XML 声明、常见中文编码依次尝试解码。"""
    candidates: list[str] = []
    m = _META_CHARSET.search(content_type or "")
    if m:
        candidates.append(m.group(1))
    head = data[:400].decode("ascii", errors="ignore")
    m = _XML_DECL_ENCODING.search(head)
    if m:
        candidates.append(m.group(1))
    candidates.extend(["utf-8", "gb18030", "big5", "latin-1"])

    seen: set[str] = set()
    for enc in candidates:
        enc = enc.strip().lower()
        if not enc or enc in seen:
            continue
        seen.add(enc)
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _sanitize_xml(text: str) -> str:
    """修复常见的非法 XML：控制字符、未转义 &、HTML 命名实体。"""
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)
    text = _CONTROL_CHARS.sub("", text)

    def replace_entity(match: re.Match[str]) -> str:
        name = match.group(1)
        if name.lower() in {"amp", "lt", "gt", "quot", "apos"}:
            return match.group(0)
        decoded = html.unescape(match.group(0))
        if decoded == match.group(0):
            return match.group(0)
        return html.escape(decoded, quote=False)

    text = _NAMED_ENTITY.sub(replace_entity, text)
    text = _BARE_AMP.sub("&amp;", text)
    return text


def _parse_date(value: str | None, lang: str = "zh") -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    iso = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            tz = BEIJING if lang == "zh" else timezone.utc
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _child_text(elem: ET.Element, names: Iterable[str]) -> str:
    wanted = {n.lower() for n in names}
    for child in elem:
        if _local(child.tag) in wanted:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _parse_link(elem: ET.Element) -> str:
    for child in elem:
        if _local(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        rel = (child.attrib.get("rel") or "alternate").lower()
        if href and rel in {"alternate", ""}:
            return href
        text = "".join(child.itertext()).strip()
        if text:
            return text
    for child in elem:
        if _local(child.tag) == "guid":
            text = "".join(child.itertext()).strip()
            if text.startswith("http"):
                return text
    return ""


def _parse_item(elem: ET.Element, source: dict) -> Article | None:
    title = clean_text(_child_text(elem, {"title"}), limit=180)
    if not title:
        return None
    url = _parse_link(elem).strip()
    summary = clean_text(
        _child_text(elem, {"description", "summary", "content", "encoded"}),
        limit=260,
    )
    published = _parse_date(
        _child_text(elem, {"pubdate", "published", "updated", "date", "created"}),
        lang=source.get("lang", "zh"),
    )
    return Article(
        title=title,
        url=url,
        summary=summary,
        source_id=source["id"],
        source_name=source["name"],
        section=source["section"],
        lang=source.get("lang", "zh"),
        weight=float(source.get("weight", 1.0)),
        published=published,
    )


def _fetch_bytes(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        elif encoding == "deflate":
            data = zlib.decompress(data)
        return data


def fetch_source(source: dict, timeout: int = 15, max_items: int = 80) -> tuple[list[Article], str | None]:
    """抓取一个源。返回 (文章列表, 错误信息)；错误不会中断整个任务。"""
    try:
        data = _fetch_bytes(source["url"], timeout=timeout)
        text = _decode(data)
        # 已经解码成 str 后，XML 声明里的 encoding 会让 ElementTree 报
        # “multi-byte encodings are not supported”，先去掉声明再解析。
        text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)
        if "<rss" not in text.lower() and "<feed" not in text.lower() and "<rdf" not in text.lower():
            snippet = re.sub(r"\s+", " ", text[:120])
            return [], f"返回内容不是 RSS/Atom（{snippet}）"
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            root = ET.fromstring(_sanitize_xml(text))

        items = [e for e in root.iter() if _local(e.tag) in {"item", "entry"}]
        articles: list[Article] = []
        for elem in items[:max_items]:
            article = _parse_item(elem, source)
            if article:
                articles.append(article)
        if not articles:
            return [], "解析成功但没有找到新闻条目"
        return articles, None
    except urllib.error.HTTPError as exc:
        return [], f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return [], f"网络错误：{reason}"
    except (TimeoutError, socket.timeout):
        return [], "请求超时"
    except ET.ParseError as exc:
        return [], f"XML 解析失败：{exc}"
    except Exception as exc:  # noqa: BLE001 - 单个源失败不应中断任务
        return [], f"{type(exc).__name__}: {exc}"


def fetch_all(sources: list[dict], timeout: int = 15, max_workers: int = 8) -> FetchResult:
    """并发抓取所有启用的源。"""
    enabled = [s for s in sources if s.get("enabled", True)]
    result = FetchResult()
    if not enabled:
        return result

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(fetch_source, source, timeout): source for source in enabled
        }
        for future in as_completed(future_map):
            source = future_map[future]
            try:
                articles, error = future.result()
            except Exception as exc:  # noqa: BLE001
                articles, error = [], f"{type(exc).__name__}: {exc}"
            if error:
                result.failed_sources += 1
                result.errors.append(f"{source['name']}：{error}")
                continue
            result.ok_sources += 1
            result.total_items += len(articles)
            result.articles.extend(articles)
    return result
