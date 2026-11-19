"""备用翻译：当 AI 编辑不可用时，把英文标题翻译成中文。

使用 MyMemory 的免费接口，带本地缓存，避免每天重复翻译同一句话。
翻译失败不会影响早报生成。
"""

from __future__ import annotations

import hashlib
import html
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .fetch import Article

_API = "https://api.mymemory.translated.net/get"
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


def _translate_text(text: str, target: str = "zh-CN", timeout: int = 8) -> str:
    text = " ".join(text.split()).strip()
    if not text:
        return ""
    if len(text) > 480:
        text = text[:480].rsplit(" ", 1)[0]
    params = urllib.parse.urlencode(
        {"q": text, "langpair": f"en|{target}"}
    )
    req = urllib.request.Request(
        f"{_API}?{params}",
        headers={"User-Agent": "MorningBrief/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if int(data.get("responseStatus", 0)) != 200:
            return ""
        translated = str(data.get("responseData", {}).get("translatedText", "")).strip()
        translated = html.unescape(translated)
        if not translated or any(word in translated.upper() for word in _STOP_WORDS):
            return ""
        if translated.lower() == text.lower():
            return ""
        return translated
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return ""


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

    unique: list[Article] = []
    seen: set[str] = set()
    for article in list(top) + [a for items in sections.values() for a in items]:
        if article.uid not in seen:
            seen.add(article.uid)
            unique.append(article)

    cache = _load_cache(cache_path)
    changed = False
    translated_count = 0
    requests = 0

    for article in unique:
        if article.lang == "zh" or article.title_zh or requests >= max_items:
            continue
        key = _key(article.title, target)
        translated = cache.get(key, "")
        if not translated:
            translated = _translate_text(article.title, target)
            requests += 1
            if translated:
                cache[key] = translated
                changed = True
        if translated:
            article.title_zh = translated
            translated_count += 1

    # 今日要闻的摘要也翻译一下，正文栏目保留原文，避免免费额度不够。
    for article in top:
        if article.lang == "zh" or article.summary_zh or not article.summary:
            continue
        snippet = article.summary[:max_summary]
        key = _key(snippet, target)
        translated = cache.get(key, "")
        if not translated:
            translated = _translate_text(snippet, target)
            requests += 1
            if translated:
                cache[key] = translated
                changed = True
        if translated:
            article.summary_zh = translated

    if changed:
        _save_cache(cache_path, cache)
    return translated_count
