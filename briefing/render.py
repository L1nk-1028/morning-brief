"""把选好的新闻渲染成 Markdown 和手机友好的 HTML。"""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .fetch import Article

BEIJING = timezone(timedelta(hours=8))
WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
MONTHS = ("", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12")


def _beijing(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(BEIJING)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING)


def date_label(dt: datetime) -> str:
    dt = _beijing(dt)
    return f"{dt.year}年{MONTHS[dt.month]}月{dt.day}日 · {WEEKDAYS[dt.weekday()]}"


def short_date(dt: datetime) -> str:
    dt = _beijing(dt)
    return f"{dt.month}月{dt.day}日"


def relative_time(published: datetime | None, now: datetime | None = None) -> str:
    if not published:
        return "时间未知"
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - published).total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"


def reading_minutes(top: list[Article], sections: dict[str, list[Article]]) -> int:
    text = "".join(a.display_title + a.display_summary for a in top)
    for items in sections.values():
        text += "".join(a.display_title + a.display_summary for a in items)
    return max(1, round(len(text) / 450))


def _md_escape(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def _md_link(article: Article) -> str:
    title = _md_escape(article.display_title)
    url = article.url.replace(" ", "%20")
    return f"[{title}]({url})" if url else title


def _lang_badge(article: Article) -> str:
    return "" if article.lang == "zh" else '<span class="badge">EN</span>'


def render_markdown(
    top: list[Article],
    sections: dict[str, list[Article]],
    config: dict,
    meta: dict,
) -> str:
    now = meta["generated_at"]
    lines: list[str] = [
        f"# {config['report']['title']}",
        "",
        f"> {date_label(now)} · {config['report'].get('greeting', '早上好')}",
        f"> 今日约 {reading_minutes(top, sections)} 分钟读完 · 共 {meta['total_items']} 条素材",
        "",
        "## ⚡ 今日要闻",
        "",
    ]
    for idx, article in enumerate(top, 1):
        lines.append(f"{idx}. {_md_link(article)} — {article.source_name}")
    lines.append("")

    for section in config["sections"]:
        if section["id"] == "top":
            continue
        items = sections.get(section["id"], [])
        if not items:
            continue
        lines.extend([f"## {section['emoji']} {section['title']}", ""])
        for article in items:
            lines.append(f"### {_md_link(article)}")
            lines.append(
                f"*{article.source_name} · {relative_time(article.published, now)}*"
            )
            lines.append("")
            if article.display_summary:
                lines.append(article.display_summary)
                lines.append("")
            if article.why:
                lines.append(f"> **为什么值得看：** {article.why}")
                lines.append("")

    lines.extend(
        [
            "---",
            "",
            f"由 Morning Brief 自动生成 · {now.astimezone(BEIJING).strftime('%H:%M')}",
            f"源：{meta['ok_sources']} 个成功 / {meta['failed_sources']} 个失败",
            "",
        ]
    )
    return "\n".join(lines)


def _html_article(article: Article, now: datetime, index: int | None = None) -> str:
    number = f'<span class="rank">{index}</span>' if index else ""
    title = html.escape(article.display_title)
    source = html.escape(article.source_name)
    summary = html.escape(article.display_summary)
    when = relative_time(article.published, now)
    href = html.escape(article.url or "#", quote=True)
    link_open = f'<a class="title-link" href="{href}" target="_blank" rel="noopener noreferrer">'
    link_close = "</a>"
    summary_html = f'<p class="summary">{summary}</p>' if summary else ""
    why_html = (
        f'<p class="why"><span>为什么值得看</span>{html.escape(article.why)}</p>'
        if article.why
        else ""
    )
    return f"""
    <article class="item">
      <div class="item-head">
        {number}
        <div class="item-body">
          <h3>{link_open}{title}{link_close}{_lang_badge(article)}</h3>
          <div class="meta"><span>{source}</span><span class="dot">·</span><span>{when}</span></div>
          {summary_html}
          {why_html}
        </div>
      </div>
    </article>"""


def render_html(
    top: list[Article],
    sections: dict[str, list[Article]],
    config: dict,
    meta: dict,
) -> str:
    now = meta["generated_at"]
    d = _beijing(now)
    date_text = date_label(now)
    minutes = reading_minutes(top, sections)
    greeting = config["report"].get("greeting", "早上好")
    title = html.escape(config["report"]["title"])

    top_items = "".join(
        f"""
      <li>
        <span class="top-index">{i:02d}</span>
        <div>
          <a href="{html.escape(a.url or '#', quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(a.display_title)}</a>
          <span class="top-source">{html.escape(a.source_name)}</span>
        </div>
      </li>"""
        for i, a in enumerate(top, 1)
    )

    sections_html: list[str] = []
    for section in config["sections"]:
        if section["id"] == "top":
            continue
        items = sections.get(section["id"], [])
        if not items:
            continue
        cards = "".join(_html_article(a, now) for a in items)
        sections_html.append(
            f"""
    <section class="section">
      <div class="section-head">
        <h2><span class="emoji">{section['emoji']}</span>{html.escape(section['title'])}</h2>
        <span class="count">{len(items)} 条</span>
      </div>
      {cards}
    </section>"""
        )

    error_note = ""
    if meta.get("errors"):
        error_note = (
            f'<details class="errors"><summary>{meta["failed_sources"]} 个源暂时不可用</summary>'
            f"<pre>{html.escape(chr(10).join(meta['errors'][:12]))}</pre></details>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#f4f1ea">
<title>{title} · {short_date(now)}</title>
<style>
  :root {{
    --bg: #f4f1ea;
    --paper: #fffdf8;
    --ink: #1f2937;
    --muted: #6b7280;
    --line: #e7e1d6;
    --accent: #b8451f;
    --accent-soft: #fbe9df;
    --shadow: 0 10px 30px rgba(76, 55, 35, .07);
  }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-text-size-adjust: 100%; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
      "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
    line-height: 1.65;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 720px; margin: 0 auto; padding: 22px 18px 48px; }}
  header.hero {{
    padding: 18px 20px 20px;
    background: linear-gradient(135deg, #fffaf1 0%, #fdf1e7 100%);
    border: 1px solid var(--line);
    border-radius: 18px;
    box-shadow: var(--shadow);
  }}
  .kicker {{
    display: inline-block;
    font-size: 12px;
    letter-spacing: .12em;
    color: var(--accent);
    background: var(--accent-soft);
    padding: 3px 9px;
    border-radius: 999px;
    margin-bottom: 10px;
  }}
  h1 {{ font-size: 27px; line-height: 1.25; margin: 0 0 8px; letter-spacing: -.02em; }}
  .date {{ color: var(--muted); font-size: 14px; margin: 0; }}
  .stats {{ margin-top: 12px; color: var(--muted); font-size: 12.5px; }}
  .top {{ margin-top: 18px; background: var(--paper); border: 1px solid var(--line); border-radius: 18px; padding: 18px 18px 8px; box-shadow: var(--shadow); }}
  .top h2 {{ font-size: 16px; margin: 0 0 12px; display: flex; align-items: center; gap: 8px; }}
  .top ol {{ list-style: none; margin: 0; padding: 0; }}
  .top li {{ display: flex; gap: 12px; padding: 11px 0; border-top: 1px dashed var(--line); }}
  .top li:first-child {{ border-top: 0; }}
  .top-index {{ font-variant-numeric: tabular-nums; font-size: 12px; font-weight: 700; color: var(--accent); padding-top: 3px; min-width: 20px; }}
  .top a {{ color: var(--ink); text-decoration: none; font-weight: 600; font-size: 15px; }}
  .top a:active {{ color: var(--accent); }}
  .top-source {{ display: block; color: var(--muted); font-size: 11.5px; margin-top: 2px; }}
  .section {{ margin-top: 28px; }}
  .section-head {{ display: flex; align-items: baseline; justify-content: space-between; margin: 0 2px 10px; }}
  .section-head h2 {{ font-size: 18px; margin: 0; letter-spacing: -.01em; }}
  .emoji {{ margin-right: 7px; }}
  .count {{ font-size: 11.5px; color: var(--muted); }}
  .item {{ background: var(--paper); border: 1px solid var(--line); border-radius: 16px; padding: 15px 16px; margin-bottom: 10px; box-shadow: 0 4px 14px rgba(76,55,35,.04); }}
  .item-head {{ display: flex; gap: 10px; }}
  .item-body {{ min-width: 0; flex: 1; }}
  .rank {{ font-size: 11px; font-weight: 700; color: var(--accent); padding-top: 4px; }}
  .item h3 {{ font-size: 16.5px; line-height: 1.45; margin: 0 0 5px; font-weight: 650; }}
  .title-link {{ color: var(--ink); text-decoration: none; }}
  .title-link:active {{ color: var(--accent); }}
  .meta {{ color: var(--muted); font-size: 11.5px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }}
  .dot {{ opacity: .5; }}
  .summary {{ color: #4b5563; font-size: 13.5px; margin: 8px 0 0; }}
  .why {{ margin: 9px 0 0; padding: 7px 9px; background: #faf4e9; border-radius: 8px; color: #6b4b2a; font-size: 12.5px; }}
  .why span {{ display: inline-block; font-weight: 700; color: var(--accent); margin-right: 6px; }}
  .badge {{ display: inline-block; vertical-align: 2px; margin-left: 6px; font-size: 9.5px; letter-spacing: .04em; color: #6b7280; border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; font-weight: 600; }}
  footer {{ margin-top: 34px; padding-top: 16px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }}
  .errors {{ margin-top: 14px; color: var(--muted); font-size: 11.5px; }}
  .errors pre {{ white-space: pre-wrap; word-break: break-word; background: #faf7f1; padding: 10px; border-radius: 10px; }}
  @media (max-width: 420px) {{
    .wrap {{ padding: 14px 12px 36px; }}
    h1 {{ font-size: 23px; }}
    header.hero {{ padding: 16px; border-radius: 15px; }}
    .item {{ padding: 13px 13px; border-radius: 14px; }}
    .item h3 {{ font-size: 15.5px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <span class="kicker">DAILY BRIEF</span>
    <h1>{title}</h1>
    <p class="date">{date_text} · {greeting}</p>
    <p class="stats">约 {minutes} 分钟读完 · {meta['ok_sources']} 个信息源 · {meta['total_items']} 条素材中精选</p>
  </header>

  <section class="top">
    <h2>⚡ 今日要闻</h2>
    <ol>{top_items}</ol>
  </section>

  {''.join(sections_html)}

  <footer>
    <div>由 Morning Brief 自动生成 · {d.strftime('%H:%M')}（北京时间）</div>
    <div>{'AI 编辑已生成中文标题、摘要与推荐理由。' if meta.get('llm_used') else '部分外媒内容保留英文原文；接入 AI 后将自动生成中文摘要。'}</div>
    {error_note}
  </footer>
</div>
</body>
</html>
"""


def write_outputs(
    output_dir: Path,
    site_dir: Path,
    markdown: str,
    page: str,
    meta: dict,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    site_dir.mkdir(parents=True, exist_ok=True)
    stamp = _beijing(meta["generated_at"]).strftime("%Y-%m-%d")
    md_path = output_dir / f"{stamp}.md"
    html_path = output_dir / f"{stamp}.html"
    latest_path = output_dir / "latest.html"
    index_path = site_dir / "index.html"
    json_path = output_dir / "latest.json"

    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(page, encoding="utf-8")
    latest_path.write_text(page, encoding="utf-8")
    index_path.write_text(page, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "generated_at": meta["generated_at"].isoformat(),
                "total_items": meta["total_items"],
                "ok_sources": meta["ok_sources"],
                "failed_sources": meta["failed_sources"],
                "errors": meta["errors"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "markdown": md_path,
        "html": html_path,
        "latest": latest_path,
        "index": index_path,
        "json": json_path,
    }
