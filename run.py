"""Morning Brief 入口：抓取 → 筛选 → 渲染 →（可选）推送。

用法：
    python run.py
    python run.py --push
    python run.py --source bbc_world,guardian_world
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from briefing.fetch import BEIJING, fetch_all
from briefing.llm import enhance
from briefing.push import PushError, push_report
from briefing.rank import prepare, select
from briefing.render import render_html, render_markdown, write_outputs

ROOT = Path(__file__).resolve().parent


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        config = json.load(fh)
    section_ids = [s["id"] for s in config.get("sections", [])]
    if len(section_ids) != len(set(section_ids)):
        raise SystemExit("config.json 里有重复的栏目 id")
    for source in config.get("sources", []):
        if source.get("section") not in section_ids:
            raise SystemExit(f"新闻源 {source.get('id')} 的 section 不存在：{source.get('section')}")
    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成我的每日早报")
    parser.add_argument("--config", default=str(ROOT / "config.json"), help="配置文件路径")
    parser.add_argument("--push", action="store_true", help="生成后推送到微信")
    parser.add_argument("--site-url", default="", help="手机阅读页地址，例如 GitHub Pages 链接")
    parser.add_argument("--source", default="", help="只抓取指定源，逗号分隔，调试用")
    parser.add_argument("--timeout", type=int, default=15, help="单个源超时秒数")
    parser.add_argument("--no-llm", action="store_true", help="跳过 AI 编辑，只用规则生成")
    return parser.parse_args()


def main() -> int:
    _configure_stdout()
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)

    sources = config.get("sources", [])
    if args.source:
        wanted = {s.strip() for s in args.source.split(",") if s.strip()}
        sources = [s for s in sources if s["id"] in wanted]
        if not sources:
            print(f"没有找到指定的源：{args.source}")
            return 1

    print(f"开始抓取：{len([s for s in sources if s.get('enabled', True)])} 个源 ...")
    fetched = fetch_all(sources, timeout=args.timeout)
    print(
        f"抓取完成：成功 {fetched.ok_sources} 个源，失败 {fetched.failed_sources} 个，"
        f"共 {fetched.total_items} 条素材"
    )
    for error in fetched.errors:
        print(f"  ! {error}")

    if not fetched.articles:
        print("没有抓到任何新闻，请检查网络或新闻源。")
        return 1

    articles = prepare(fetched.articles, config)
    top, sections = select(articles, config)
    if not top and not any(sections.values()):
        print("素材都太旧或没有匹配栏目，未生成早报。")
        return 1

    now = datetime.now(timezone.utc)
    if args.no_llm:
        config.setdefault("llm", {})["enabled"] = False
    top, sections, llm_meta = enhance(top, sections, config, now)
    if llm_meta.get("llm_used"):
        print("AI 编辑：已生成中文标题、摘要与推荐理由")
    elif llm_meta.get("llm_error"):
        print(f"AI 编辑跳过：{llm_meta['llm_error']}")

    meta = {
        "generated_at": now,
        "total_items": fetched.total_items,
        "ok_sources": fetched.ok_sources,
        "failed_sources": fetched.failed_sources,
        "errors": fetched.errors,
        "llm_used": llm_meta.get("llm_used", False),
        "llm_error": llm_meta.get("llm_error", ""),
    }
    markdown = render_markdown(top, sections, config, meta)
    page = render_html(top, sections, config, meta)

    output_dir = ROOT / config["report"].get("output_dir", "output")
    site_dir = ROOT / config["report"].get("site_dir", "docs")
    paths = write_outputs(output_dir, site_dir, markdown, page, meta)

    # 归档一份按日期命名的网页，方便以后回看。
    archive = site_dir / f"{now.astimezone(BEIJING).strftime('%Y-%m-%d')}.html"
    try:
        archive.write_text(page, encoding="utf-8")
    except OSError:
        pass

    print("")
    print(f"早报已生成：{paths['latest']}")
    print(f"手机阅读页：{paths['index']}")
    print(f"Markdown：{paths['markdown']}")
    print("")
    print("今日要闻：")
    for idx, article in enumerate(top, 1):
        print(f"  {idx}. {article.display_title}  [{article.source_name}]")

    should_push = args.push or bool(config.get("push", {}).get("enabled"))
    if should_push:
        title = f"{config['report']['title']} · {now.astimezone().strftime('%m月%d日')}"
        try:
            result = push_report(config, title, markdown, site_url=args.site_url)
            print(f"微信推送：{result.message}")
        except PushError as exc:
            print(f"微信推送失败：{exc}")
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
