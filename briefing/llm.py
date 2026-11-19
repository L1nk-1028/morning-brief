"""可选的 AI 编辑层。

优先使用 GitHub Models（GitHub Actions 里自带 GITHUB_TOKEN，免费），
也支持 DeepSeek 的 OpenAI 兼容接口。没有密钥时自动跳过，早报仍能生成。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from .fetch import Article

class LLMError(RuntimeError):
    pass


def _provider_settings(config: dict) -> tuple[str, str, list[str], str]:
    llm = config.get("llm", {})
    provider = llm.get("provider", "github")
    if provider == "github":
        base_url = llm.get("base_url", "https://models.github.ai/inference")
        model = llm.get("model", "openai/gpt-4o-mini")
        key_env = llm.get("api_key_env", "GITHUB_TOKEN")
    elif provider == "deepseek":
        base_url = llm.get("base_url", "https://api.deepseek.com")
        model = llm.get("model", "deepseek-chat")
        key_env = llm.get("api_key_env", "DEEPSEEK_API_KEY")
    else:
        raise LLMError(f"不支持的 AI 服务：{provider}")

    key = os.environ.get(key_env, "").strip()
    if not key:
        raise LLMError(f"没有找到环境变量 {key_env}，跳过 AI 编辑")

    models = [model]
    for fallback in llm.get("fallback_models", []):
        if fallback and fallback not in models:
            models.append(str(fallback))
    return provider, base_url.rstrip("/"), models, key


def _chat(config: dict, messages: list[dict[str, str]]) -> str:
    provider, base_url, models, key = _provider_settings(config)
    url = f"{base_url}/chat/completions"
    timeout = int(config.get("llm", {}).get("timeout", 120))
    last_error = ""

    for model in models:
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.25,
            "max_tokens": 4000,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "MorningBrief/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            last_error = f"{provider} 模型 {model} HTTP {exc.code}：{detail}"
            # 模型不存在/参数不支持时换下一个模型；权限/限流问题直接报错。
            if exc.code in (400, 404) and model != models[-1]:
                continue
            raise LLMError(last_error) from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"{provider} 网络错误：{exc.reason}") from exc
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError(f"AI 返回格式异常：{raw[:300]}") from exc

    raise LLMError(last_error or "没有可用的 AI 模型")


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LLMError(f"AI 没有返回合法 JSON：{text[:300]}") from exc
        raise LLMError(f"AI 没有返回 JSON：{text[:300]}")


def _payload(article: Article) -> dict[str, Any]:
    return {
        "id": article.uid,
        "section": article.section,
        "source": article.source_name,
        "lang": article.lang,
        "title": article.title,
        "summary": article.summary[:320],
        "published": article.published.isoformat() if article.published else "",
    }


def _build_messages(
    unique: list[Article],
    config: dict,
    now: datetime,
) -> list[dict[str, str]]:
    sections = [
        {"id": s["id"], "title": s["title"], "limit": s.get("limit", 4)}
        for s in config["sections"]
        if s["id"] != "top"
    ]
    top_count = config["report"].get("top_count", 5)
    system = (
        "你是一名资深中文早报编辑。读者是一位中文母语的 AI 初学者，"
        "关注 AI 与前沿科技、国际政治与地缘、财经与市场、科学太空、体育、"
        "游戏动漫与流行文化。你的任务是把给定的新闻素材编辑成准确、简洁、"
        "有信息量的中文早报。\n"
        "硬性要求：\n"
        "1. 只能使用给定素材，不编造事实、数字、引语或链接。\n"
        "2. 每条输出中文标题（不超过 30 字）、2-3 句中文摘要（不超过 120 字）、"
        "一句“为什么值得看”（不超过 45 字）。\n"
        "3. 英文素材要翻译成自然中文，专有名词保留常用译名或原名。\n"
        "4. 今日要闻选最重要、最有全球或国内影响力的 5 条，尽量覆盖不同地区/领域，"
        "不要选日常行情、产品促销、娱乐八卦、历史上的今天。\n"
        "5. 只输出严格 JSON，不要 Markdown 代码块，不要解释。"
    )
    user = (
        f"今天是 {now.strftime('%Y年%m月%d日')}（北京时间）。\n"
        f"请从以下候选中选出今日要闻 {top_count} 条，并为每个栏目选出不超过限额的条目。\n"
        f"栏目：{json.dumps(sections, ensure_ascii=False)}\n"
        f"候选：{json.dumps([_payload(a) for a in unique], ensure_ascii=False)}\n\n"
        "输出格式：\n"
        "{\n"
        '  "top": ["id1", "id2"],\n'
        '  "sections": {"china": ["id"], "world": ["id"], "tech": ["id"], "finance": ["id"], "science": ["id"], "sports": ["id"], "culture": ["id"]},\n'
        '  "items": {"id": {"title_zh": "中文标题", "summary_zh": "中文摘要", "why": "为什么值得看"}}\n'
        "}\n"
        "注意：top 和 sections 里的 id 必须来自候选；items 要覆盖所有被选中的 id。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def enhance(
    top: list[Article],
    sections: dict[str, list[Article]],
    config: dict,
    now: datetime,
) -> tuple[list[Article], dict[str, list[Article]], dict[str, Any]]:
    """调用 AI 生成中文标题/摘要。失败时原样返回，不影响早报生成。"""
    if not config.get("llm", {}).get("enabled", False):
        return top, sections, {"llm_used": False, "llm_error": ""}

    unique: list[Article] = []
    seen: set[str] = set()
    for article in list(top) + [a for items in sections.values() for a in items]:
        if article.uid and article.uid not in seen:
            seen.add(article.uid)
            unique.append(article)
    if not unique:
        return top, sections, {"llm_used": False, "llm_error": "没有候选"}

    try:
        content = _chat(config, _build_messages(unique, config, now))
        data = _extract_json(content)
    except LLMError as exc:
        return top, sections, {"llm_used": False, "llm_error": str(exc)}

    by_id = {a.uid: a for a in unique}
    items = data.get("items") or {}
    if not isinstance(items, dict):
        return top, sections, {"llm_used": False, "llm_error": "AI 返回的 items 不是对象"}

    for article in unique:
        item = items.get(article.uid)
        if not isinstance(item, dict):
            continue
        title = str(item.get("title_zh") or "").strip()
        summary = str(item.get("summary_zh") or "").strip()
        why = str(item.get("why") or "").strip()
        if title:
            article.title_zh = title
        if summary:
            article.summary_zh = summary
        if why:
            article.why = why

    def _map_ids(ids: Any) -> list[Article]:
        result: list[Article] = []
        if not isinstance(ids, list):
            return result
        for raw_id in ids:
            article = by_id.get(str(raw_id))
            if article and article not in result:
                result.append(article)
        return result

    new_top = _map_ids(data.get("top"))
    if len(new_top) < int(config["report"].get("top_count", 5)):
        chosen = {id(a) for a in new_top}
        for article in top:
            if id(article) not in chosen:
                new_top.append(article)
            if len(new_top) >= int(config["report"].get("top_count", 5)):
                break
    new_top = new_top[: int(config["report"].get("top_count", 5))]

    raw_sections = data.get("sections") or {}
    new_sections: dict[str, list[Article]] = {}
    for section in config["sections"]:
        if section["id"] == "top":
            continue
        sid = section["id"]
        picked = [a for a in _map_ids(raw_sections.get(sid)) if a.section == sid]
        if not picked:
            picked = sections.get(sid, [])
        new_sections[sid] = picked[: int(section.get("limit", 4))]

    return new_top, new_sections, {"llm_used": True, "llm_error": ""}
