"""把项目上传到 GitHub，并尝试开启 Pages、触发一次 Actions。

用法（在项目目录）：
    python publish_github.py --repo morning-brief

Token 只从环境变量 GITHUB_TOKEN 读取；没有时会在终端里隐藏输入。
建议用 classic token，勾选 repo 和 workflow，设置 7 天过期，用完即删。
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
ROOT = Path(__file__).resolve().parent
INCLUDE_FILES = {
    "config.json",
    "run.py",
    "README.md",
    "PREFERENCES.md",
    "run.ps1",
    "preview.ps1",
    "publish_github.py",
    "publish.ps1",
    "publish.bat",
    "test_push.py",
    "test_push.bat",
}
INCLUDE_DIRS = ("briefing/", "docs/", "output/", ".github/")
SKIP_PARTS = {".git", "__pycache__", ".venv", "node_modules"}


class GitHubError(RuntimeError):
    pass


def api(
    method: str,
    path: str,
    token: str,
    payload: dict | None = None,
    ok: tuple[int, ...] = (200, 201, 204),
) -> tuple[int, dict | list | None]:
    url = API + path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "MorningBrief-Publisher/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        if exc.code in ok:
            return exc.code, None
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise GitHubError(f"{method} {path} -> HTTP {exc.code}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise GitHubError(f"连接 GitHub API 失败：{exc.reason}") from exc


def collect_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if rel in INCLUDE_FILES or rel.startswith(INCLUDE_DIRS):
            files.append(path)
    return sorted(files, key=lambda p: p.relative_to(ROOT).as_posix())


def ensure_repo(token: str, owner: str, repo: str) -> None:
    status, _ = api("GET", f"/repos/{owner}/{repo}", token, ok=(200, 404))
    if status == 200:
        print(f"仓库已存在：https://github.com/{owner}/{repo}")
        return
    print(f"仓库不存在，正在创建 {owner}/{repo} ...")
    api(
        "POST",
        "/user/repos",
        token,
        {
            "name": repo,
            "private": False,
            "has_issues": False,
            "has_wiki": False,
            "auto_init": False,
        },
    )
    print("仓库创建成功。")


def ensure_main_branch(token: str, owner: str, repo: str) -> None:
    """空仓库没有 main 分支时，先创建一个初始提交。"""
    status, _ = api("GET", f"/repos/{owner}/{repo}/branches/main", token, ok=(200, 404))
    if status == 200:
        return
    print("仓库还是空的，先创建 main 分支的初始提交 ...")
    content = base64.b64encode(b"# morning-brief\n").decode("ascii")
    api(
        "PUT",
        f"/repos/{owner}/{repo}/contents/README.md",
        token,
        {"message": "Initial commit", "content": content},
    )


def upload_file(token: str, owner: str, repo: str, path: Path) -> None:
    rel = path.relative_to(ROOT).as_posix()
    content = base64.b64encode(path.read_bytes()).decode("ascii")
    payload: dict = {
        "message": f"Add {rel}",
        "content": content,
        "branch": "main",
    }
    status, existing = api(
        "GET",
        f"/repos/{owner}/{repo}/contents/{urllib.parse.quote(rel)}?ref=main",
        token,
        ok=(200, 404),
    )
    if status == 200 and isinstance(existing, dict) and existing.get("sha"):
        payload["sha"] = existing["sha"]
    api("PUT", f"/repos/{owner}/{repo}/contents/{urllib.parse.quote(rel)}", token, payload)


def enable_pages(token: str, owner: str, repo: str) -> None:
    status, _ = api("GET", f"/repos/{owner}/{repo}/pages", token, ok=(200, 404))
    if status == 200:
        print("GitHub Pages 已经开启。")
        return
    print("正在开启 GitHub Pages（Source = GitHub Actions）...")
    try:
        api(
            "POST",
            f"/repos/{owner}/{repo}/pages",
            token,
            {"build_type": "workflow"},
            ok=(201, 204, 409, 422),
        )
        print("Pages 已开启，或已由其他方式开启。")
    except GitHubError as exc:
        print(f"自动开启 Pages 失败，稍后可在仓库 Settings → Pages 手动设置。\n{exc}")


def trigger_workflow(token: str, owner: str, repo: str) -> None:
    print("正在触发一次 Daily Morning Brief ...")
    for attempt in range(1, 7):
        try:
            api(
                "POST",
                f"/repos/{owner}/{repo}/actions/workflows/daily.yml/dispatches",
                token,
                {"ref": "main"},
                ok=(204,),
            )
            print("已触发。打开 Actions 页面可以看到运行进度。")
            return
        except GitHubError as exc:
            if attempt == 6:
                print(f"触发失败（可稍后在 Actions 页面手动点 Run workflow）：\n{exc}")
                return
            print(f"工作流还没准备好，{5} 秒后重试（{attempt}/6）...")
            time.sleep(5)


def main() -> int:
    parser = argparse.ArgumentParser(description="上传 Morning Brief 到 GitHub")
    parser.add_argument("--repo", default="morning-brief", help="仓库名")
    parser.add_argument("--no-pages", action="store_true", help="不自动开启 Pages")
    parser.add_argument("--no-run", action="store_true", help="不自动触发 Actions")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("粘贴 GitHub Token（输入时不显示，粘贴后回车）：").strip()
    if not token:
        print("没有提供 Token，退出。")
        return 1

    try:
        _, user = api("GET", "/user", token)
        if not isinstance(user, dict) or not user.get("login"):
            raise GitHubError("Token 无法读取用户信息")
        owner = user["login"]
        print(f"已登录：{owner}")
        ensure_repo(token, owner, args.repo)
        ensure_main_branch(token, owner, args.repo)

        files = collect_files()
        print(f"准备上传 {len(files)} 个文件 ...")
        failed: list[str] = []
        for idx, path in enumerate(files, 1):
            rel = path.relative_to(ROOT).as_posix()
            print(f"  [{idx}/{len(files)}] {rel}")
            for attempt in range(1, 4):
                try:
                    upload_file(token, owner, args.repo, path)
                    break
                except GitHubError as exc:
                    if attempt == 3:
                        print(f"    ! 上传失败：{exc}")
                        failed.append(rel)
                    else:
                        print("    ! 网络或接口波动，2 秒后重试 ...")
                        time.sleep(2)
            time.sleep(0.15)

        if failed:
            print("")
            print(f"有 {len(failed)} 个文件没有上传成功：")
            for rel in failed:
                print(f"  - {rel}")
            print("请重新运行 publish.bat；已上传的文件会自动跳过/覆盖。")
            return 3

        print(f"全部 {len(files)} 个文件上传完成。")
        if not args.no_pages:
            enable_pages(token, owner, args.repo)
        if not args.no_run:
            trigger_workflow(token, owner, args.repo)

        print("")
        print("完成。")
        print(f"仓库：https://github.com/{owner}/{args.repo}")
        print(f"网页：https://{owner}.github.io/{args.repo}/")
        print(f"Actions：https://github.com/{owner}/{args.repo}/actions")
        print("提示：Pages 第一次部署可能需要 1-3 分钟。")
        return 0
    except GitHubError as exc:
        print(f"\n失败：{exc}")
        print("请检查 Token 是否过期、是否有 repo / workflow 权限。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
