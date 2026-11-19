"""备用翻译：当 AI 编辑不可用时，把英文标题翻译成中文。

使用 MyMemory 的免费接口，带本地缓存。为了避开免费的每日请求额度，
把多条标题用分隔符拼成一次请求批量翻译，失败时再逐条重试。
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .fetch import Article

_API = "https://api.mymemory.translated.net/get"
_BATCH_SEP = "\n@@@\n"
_STOP_WORDS = (
    "MYMEMORY WARNING",
    "YOU USED ALL AVAILABLE FREE TRANSLATIONS",
    "QUERY LENGTH LIMIT",
)


def _key(text: str, target: str) -> str:
    return hashlib.sha1(f"{target}|{text}".encode("utf-8")).hexdigest()


def _load_cache(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(path: Path, cache: dict[str, str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _params(query: str, target: str) -> dict[str, str]:
    params = {"q": query, "langpair": f"en|{target}"}
    # MyMemory 支持用 de 参数登记邮箱，免费额度会从 5000 字符/天提高。
    email = os.environ.get("MYMEMORY_EMAIL", "").strip()
    if email:
        params["de"] = email
    return params


def _request(query: str, target: str, timeout: int) -> str:
    url = f"{_API}?{urllib.parse.urlencode(_params(query, target))}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MorningBrief/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    if int(data.get("responseStatus", 0)) != 200:
        return ""
    translated = str(data.get("responseData", {}).get("translatedText", "")).strip()
    translated = html.unescape(translated)
    if not translated or any(word in translated.upper() for word in _STOP_WORDS):
        return ""
    return translated


def _translate_text(text: str, target: str = "zh-CN", timeout: int = 8) -> str:
    text = " ".join(text.split()).strip()
    if not text:
        return ""
    if len(text) > 480:
        text = text[:480].rsplit(" ", 1)[0]
    try:
        translated = _request(text, target, timeout)
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return ""
    if translated.lower() == text.lower():
        return ""
    return translated


def _translate_batch(texts: list[str], target: str = "zh-CN", timeout: int = 15) -> list[str]:
    """一次翻译多条标题，返回与输入等长的列表；失败时返回空字符串占位。"""
    cleaned = [" ".join(t.split()).strip() for t in texts]
    if any(not t for t in cleaned):
        return [""] * len(texts)
    query = _BATCH_SEP.join(cleaned)
    if len(query) > 1800:
        return [""] * len(texts)
    try:
        translated = _request(query, target, timeout)
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return [""] * len(texts)
    parts = [p.strip() for p in re.split(r"\s*@@@\s*", translated)]
    if len(parts) != len(texts):
        return [""] * len(texts)
    return [p if p and p.lower() != t.lower() else "" for p, t in zip(parts, cleaned)]


def translate_articles(
    top: list[Article],
    sections: dict[str, list[Article]],
    cache_path: Path,
    config: dict,
) -> int:
    settings = config.get("translation", {})
    if not settings.get("enabled", True):
        return 0
    target = settings.get("target", "zh-CN")
    max_items = int(settings.get("max_items", 40))
    max_summary = int(settings.get("max_summary_chars", 180))
    batch_size = max(1, int(settings.get("batch_size", 5)))

    unique: list[Article] = []
    seen: set[str] = set()
    for article in list(top) + [a for items in sections.values() for a in items]:
        if article.uid not in seen:
            seen.add(article.uid)
            unique.append(article)

    cache = _load_cache(cache_path)
    changed = False
    translated_count = 0

    # 先处理缓存，收集还需要翻译的标题。
    pending: list[tuple[Article, str, str]] = []
    for article in unique:
        if article.lang == "zh" or article.title_zh:
            continue
        key = _key(article.title, target)
        cached = cache.get(key, "")
        if cached:
            article.title_zh = cached
            translated_count += 1
        elif len(pending) < max_items:
            pending.append((article, article.title, key))

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        translated_list = _translate_batch([item[1] for item in batch], target)
        for (article, source, key), translated in zip(batch, translated_list):
            if not translated:
                translated = _translate_text(source, target)
            if translated:
                article.title_zh = translated
                cache[key] = translated
                changed = True
                translated_count += 1

    # 今日要闻的摘要也翻译，正文栏目保留原文，避免免费额度不够。
    for article in top:
        if article.lang == "zh" or article.summary_zh or not article.summary:
            continue
        snippet = article.summary[:max_summary]
        key = _key(snippet, target)
        translated = cache.get(key, "")
        if not translated:
            translated = _translate_text(snippet, target)
            if translated:
                cache[key] = translated
                changed = True
        if translated:
            article.summary_zh = translated

    if changed:
        _save_cache(cache_path, cache)
    return translated_count
