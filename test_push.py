"""本地测试 Server酱 推送，不会保存 SendKey。"""

from __future__ import annotations

import getpass
import sys

from briefing.push import PushError, push_serverchan

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

print("这个脚本只发一条测试消息到你的微信，不会保存 SendKey。")
key = getpass.getpass("粘贴 Server酱 SendKey（输入时不显示）：").strip()
if not key:
    print("没有输入 SendKey，退出。")
    raise SystemExit(1)

try:
    result = push_serverchan(
        key,
        "早报推送测试",
        "如果你在微信里看到这条消息，说明 Server酱 已经配置成功。\n\n接下来把 SendKey 加到 GitHub Secret 即可。",
    )
    print(result.message)
except PushError as exc:
    print(f"推送失败：{exc}")
    raise SystemExit(2)
