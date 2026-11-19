"""把早报推送到微信。

默认使用 Server酱（方糖服务号），也保留了 PushPlus 的实现。
密钥只从环境变量读取，不写进代码或配置文件。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class PushError(RuntimeError):
    pass


@dataclass
class PushResult:
    provider: str
    ok: bool
    message: str
    raw: dict | None = None


def _post_form(url: str, data: dict[str, str], timeout: int = 20) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "MorningBrief/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PushError(f"推送服务返回了非 JSON 内容：{text[:200]}") from exc


def _post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "MorningBrief/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PushError(f"推送服务返回了非 JSON 内容：{text[:200]}") from exc


def push_serverchan(sendkey: str, title: str, markdown: str, short: str = "") -> PushResult:
    if not sendkey:
        raise PushError("缺少 Server酱 SendKey")
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    payload = {"title": title[:32], "desp": markdown}
    if short:
        payload["short"] = short[:60]
    try:
        data = _post_form(url, payload)
    except urllib.error.HTTPError as exc:
        raise PushError(f"Server酱 HTTP {exc.code}") from exc
    code = data.get("code")
    if code not in (0, "0", None):
        raise PushError(f"Server酱返回错误：{data.get('message') or data}")
    return PushResult("serverchan", True, "推送成功", data)


def push_pushplus(token: str, title: str, markdown: str) -> PushResult:
    if not token:
        raise PushError("缺少 PushPlus token")
    payload = {
        "token": token,
        "title": title[:100],
        "content": markdown,
        "template": "markdown",
    }
    try:
        data = _post_json("https://www.pushplus.plus/send", payload)
    except urllib.error.HTTPError as exc:
        raise PushError(f"PushPlus HTTP {exc.code}") from exc
    if data.get("code") not in (200, "200", None):
        raise PushError(f"PushPlus 返回错误：{data.get('msg') or data}")
    return PushResult("pushplus", True, "推送成功", data)


def push_report(
    config: dict,
    title: str,
    body: str,
    short: str = "",
    site_url: str = "",
) -> PushResult:
    provider = config.get("push", {}).get("provider", "serverchan")
    default_env = "PUSHPLUS_TOKEN" if provider == "pushplus" else "SERVERCHAN_SENDKEY"
    env_name = config.get("push", {}).get("sendkey_env", default_env)
    key = os.environ.get(env_name, "").strip()

    if site_url and site_url not in body:
        body += f"\n\n[在手机上阅读排版版]({site_url})"

    if provider == "serverchan":
        return push_serverchan(key, title, body, short=short)
    if provider == "pushplus":
        return push_pushplus(key, title, body)
    raise PushError(f"不支持的推送方式：{provider}")
