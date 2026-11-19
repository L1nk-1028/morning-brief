"""去重、打分、按栏目挑选新闻。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable

from .fetch import Article

_PUNCT = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
_BRACKET_PREFIX = re.compile(r"^[【\[（(][^】\]）)]{1,24}[】\]）)]\s*")

# 栏目在“今日要闻”里的优先级：时政优先，体育/文化更适合放在各自栏目。
SECTION_PRIORITY = {
    "china": 1.25,
    "world": 1.35,
    "tech": 1.05,
    "finance": 0.95,
    "science": 0.90,
    "sports": 0.70,
    "culture": 0.65,
}

HARD_SOURCE_IDS = {
    "chinanews_china", "chinanews_world", "un_news_zh", "bbc_zh", "bbc_world",
    "guardian_world", "npr_world", "aljazeera_all", "france24", "un_news",
    "dw_zh", "rfi_zh", "wsj_markets", "ft_home",
}

# 判断“今天这件事大不大”的词。比兴趣关键词更强调硬新闻。
IMPORTANT_TERMS = [
    "习近平", "特朗普", "普京", "会晤", "峰会", "apec", "g20", "联合国",
    "北约", "欧盟", "战争", "停火", "袭击", "空袭", "制裁", "选举", "大选",
    "政变", "核武", "核协议", "核电站", "关税", "美联储", "加息", "降息",
    "通胀", "衰退", "地震", "海啸", "台风", "洪水", "气候", "cop", "cop31",
    "加沙", "以色列", "哈马斯", "内塔尼亚胡",
    "人工智能", "芯片", "半导体", "机器人", "火箭", "火星", "月球", "登月",
    "量子", "超导",
    "xi", "trump", "putin", "ceasefire", "war", "strike", "sanctions",
    "election", "fed", "rate", "tariff", "recession", "nasa", "spacex",
    "mars", "moon", "climate", "cop31", "summit", "gaza", "israel", "hamas",
    "netanyahu", "ai", "chip", "semiconductor",
]

# 这类“日常消息”放在栏目里没问题，但不适合占据今日要闻。
ROUTINE_TERMS = [
    "中间价", "开盘", "收盘", "逆回购", "涨跌", "涨停", "跌停",
    "气温", "天气", "降水", "冷空气", "联赛", "赛事", "门店", "发售",
    "评测", "攻略", "早报｜", "受访者", "调查", "问卷", "科普", "考古",
    "旅游", "乡村", "侨村", "消防", "健康", "养生", "咖啡", "骨头",
    "校园", "课堂", "App", "应用推荐",
    "小幅", "微涨", "微跌", "收涨", "收跌", "个股", "板块", "行情", "快讯",
    "on this day", "this day in", "anniversary", "历史上的今天", "回顾", "纪念",
]


def normalize_title(title: str) -> str:
    text = title.lower().strip()
    text = _BRACKET_PREFIX.sub("", text)
    text = _PUNCT.sub("", text)
    return text


def _keyword_hit(text: str, keyword: str) -> bool:
    kw = keyword.lower().strip()
    if not kw:
        return False
    if re.fullmatch(r"[a-z0-9+#.\- ]+", kw):
        return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", text) is not None
    return kw in text


def _count_terms(text: str, terms: list[str]) -> int:
    return sum(1 for term in terms if _keyword_hit(text, term))


def _scores(
    article: Article,
    now: datetime,
    interests: dict,
    max_age_hours: int,
    allow_undated: bool,
) -> tuple[float, float] | None:
    if article.published:
        age_hours = max(0.0, (now - article.published).total_seconds() / 3600)
        if age_hours > max_age_hours:
            return None
        recency = max(0.0, 1.0 - age_hours / max_age_hours)
    else:
        if not allow_undated:
            return None
        recency = 0.1

    # 栏目内排序分：新鲜度 + 来源权重 + 兴趣匹配。
    score = article.weight + recency * 2.2
    text = f"{article.title} {article.summary}".lower()
    hits = 0
    for keywords in interests.values():
        for keyword in keywords:
            if _keyword_hit(text, keyword):
                hits += 1
    score += min(hits * 0.14, 2.0)

    # 栏目内的偏好加权：让用户真正关心的具体对象排到前面。
    if article.section == "sports" and any(
        _keyword_hit(text, kw)
        for kw in ("nba", "f1", "paul george", "kawhi leonard", "verstappen", "hamilton", "leclerc", "norris")
    ):
        score += 1.2
    if article.section == "culture" and any(
        _keyword_hit(text, kw)
        for kw in ("cs2", "counter-strike", "faze", "esports", "电子竞技", "海贼王", "one piece")
    ):
        score += 1.2
    if article.section == "tech" and any(
        _keyword_hit(text, kw)
        for kw in ("iphone", "ipad", "macbook", "airpods", "sony", "索尼", "playstation", "ps5", "samsung", "三星", "华为", "小米", "耳机", "手表", "显卡")
    ):
        score += 0.8

    if len(article.title) < 8:
        score -= 0.4
    if not article.url:
        score -= 0.25

    # 今日要闻排序分：更看重“事件重要性”，而不是谁刚更新。
    title_text = article.title.lower()
    importance = _count_terms(title_text, IMPORTANT_TERMS)
    routine = _count_terms(title_text, ROUTINE_TERMS)
    section_priority = SECTION_PRIORITY.get(article.section, 0.8)
    source_bonus = 0.2 if article.source_id in HARD_SOURCE_IDS else 0.0
    top_score = (
        importance * 2.4
        + section_priority
        + recency * 0.9
        + article.weight * 0.15
        + source_bonus
        - routine * 2.0
    )
    # 问句/解释性标题多半是特稿，不如硬新闻适合放在“今日要闻”。
    if title_text.rstrip().endswith("?") or re.match(
        r"^(why|how|what|could|would|should|is|are|can)\b", title_text
    ):
        top_score -= 1.2

    return round(score, 4), round(top_score, 4)


def _dedupe(articles: Iterable[Article]) -> list[Article]:
    """按标题指纹和链接去重，保留分数更高的那条。"""
    kept: list[Article] = []
    seen_titles: dict[str, Article] = {}
    seen_urls: set[str] = set()

    for article in sorted(articles, key=lambda a: a.score, reverse=True):
        title_key = normalize_title(article.title)
        url_key = article.url.split("#", 1)[0].strip().lower()
        if url_key and url_key in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        # 处理“同一件事，标题只差几个字”的常见情况。
        if len(title_key) >= 16 and any(
            title_key in key or key in title_key for key in seen_titles if len(key) >= 16
        ):
            continue

        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles[title_key] = article
        kept.append(article)
    return kept


def _take_diverse(
    pool: list[Article],
    limit: int,
    max_per_source: int = 2,
    allow_fill: bool = True,
) -> list[Article]:
    """同一来源最多取几条，让栏目里的声音更丰富。"""
    picked: list[Article] = []
    source_count: dict[str, int] = {}
    for article in pool:
        if source_count.get(article.source_id, 0) >= max_per_source:
            continue
        picked.append(article)
        source_count[article.source_id] = source_count.get(article.source_id, 0) + 1
        if len(picked) >= limit:
            return picked

    if not allow_fill:
        return picked

    # 如果因为来源限制没凑够，再放开限制补足。
    chosen_ids = {id(a) for a in picked}
    for article in pool:
        if id(a) in chosen_ids:
            continue
        picked.append(article)
        if len(picked) >= limit:
            break
    return picked


TOPIC_RULES = {
    "trilateral": (
        {"xi", "trump", "putin", "习近平", "特朗普", "普京", "trilateral", "three-way", "china", "russia", "中国", "俄罗斯"},
        2,
    ),
    "gaza": ({"gaza", "israel", "hamas", "netanyahu", "加沙", "以色列", "哈马斯", "内塔尼亚胡"}, 1),
    "ukraine": ({"ukraine", "russia", "乌克兰", "俄罗斯"}, 2),
    "cop31": ({"cop31", "climate", "气候"}, 1),
    "apec": ({"apec", "深圳"}, 1),
}


def _topic_keys(article: Article) -> set[str]:
    text = article.title.lower()
    keys: set[str] = set()
    for name, (terms, min_hits) in TOPIC_RULES.items():
        if sum(1 for term in terms if _keyword_hit(text, term)) >= min_hits:
            keys.add(name)
    return keys


def prepare(articles: list[Article], config: dict, now: datetime | None = None) -> list[Article]:
    now = now or datetime.now(timezone.utc)
    max_age = int(config["report"].get("max_age_hours", 36))
    interests = config.get("interests", {})
    allow_undated = bool(config["report"].get("allow_undated", False))

    scored: list[Article] = []
    for article in articles:
        scores = _scores(article, now, interests, max_age, allow_undated)
        if scores is None:
            continue
        article.score, article.top_score = scores
        raw = f"{article.source_id}|{article.url}|{article.title}"
        article.uid = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        scored.append(article)

    scored.sort(key=lambda a: a.score, reverse=True)
    return _dedupe(scored)


_SCIENCE_NOISE = (
    "streaming", "star trek", "paramount", "trailer", "where to watch",
    "movie", "tv show", "review", "deal", "watching",
    "on this day", "this day in", "anniversary",
)
_SPORTS_NOISE = ("survey", "poll", "受访", "调查", "问卷")
_MINOR_FINANCE = ("中间价", "逆回购", "小幅", "微涨", "微跌")


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_keyword_hit(text, term) for term in terms)


def select(articles: list[Article], config: dict) -> tuple[list[Article], dict[str, list[Article]]]:
    """返回 (今日要闻, {栏目: 文章列表})。"""
    sections = [s for s in config["sections"] if s["id"] != "top"]
    grouped: dict[str, list[Article]] = {s["id"]: [] for s in sections}
    for article in articles:
        if article.section in grouped:
            grouped[article.section].append(article)

    selected: dict[str, list[Article]] = {}
    for section in sections:
        pool = grouped.get(section["id"], [])
        sid = section["id"]
        filtered = pool
        if sid == "science":
            filtered = [a for a in pool if not _has_any(a.title.lower(), _SCIENCE_NOISE)]
        elif sid == "sports":
            filtered = [a for a in pool if not _has_any(a.title.lower(), _SPORTS_NOISE)]
        elif sid == "finance":
            filtered = [a for a in pool if not _has_any(a.title.lower(), _MINOR_FINANCE)]
        if filtered:
            selected[sid] = _take_diverse(
                filtered, int(section.get("limit", 4)), allow_fill=False
            )
        else:
            selected[sid] = _take_diverse(pool, int(section.get("limit", 4)))

    # 今日要闻从全部候选里挑，不受各栏目条数限制；
    # 再用“每栏目最多 3 条、每来源最多 1 条”保证视角多元。
    candidates = sorted(articles, key=lambda a: a.top_score, reverse=True)

    top_limit = int(config["report"].get("top_count", 5))
    top: list[Article] = []
    section_count: dict[str, int] = {}
    source_count: dict[str, int] = {}
    used_topics: set[str] = set()
    for article in candidates:
        if section_count.get(article.section, 0) >= 3:
            continue
        if source_count.get(article.source_id, 0) >= 1:
            continue
        topics = _topic_keys(article)
        if topics & used_topics:
            continue
        top.append(article)
        used_topics.update(topics)
        section_count[article.section] = section_count.get(article.section, 0) + 1
        source_count[article.source_id] = source_count.get(article.source_id, 0) + 1
        if len(top) >= top_limit:
            break

    # 候选不足时放宽来源/栏目限制补足，但仍然不允许同一话题重复。
    if len(top) < top_limit:
        chosen = {id(a) for a in top}
        for article in candidates:
            if id(article) in chosen:
                continue
            topics = _topic_keys(article)
            if topics & used_topics:
                continue
            top.append(article)
            used_topics.update(topics)
            chosen.add(id(article))
            if len(top) >= top_limit:
                break

    return top, selected
