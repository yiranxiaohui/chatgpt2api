"""FlareSolverr 集成。

当直连 ``chatgpt.com`` / ``auth.openai.com`` 被 Cloudflare 浏览器质询
（"Just a moment..." 盾页）拦截时，调用 FlareSolverr 的无头浏览器过盾，
取回 ``cf_clearance`` cookie 与匹配的 User-Agent，注入回 curl_cffi session 后重试。

关键约束：``cf_clearance`` 与「出口 IP + User-Agent」强绑定，因此
  1. 默认把本服务的 proxy 透传给 FlareSolverr，保证两者出口 IP 一致；
  2. 注入 ``cf_clearance`` 后，整条会话必须改用 FlareSolverr 返回的 User-Agent，
     否则 Cloudflare 会判定指纹不一致而再次质询。

仅在「注册 / 登录」流程接入（见 services/register/openai_register.py、
services/account_service.py、services/oauth_login_service.py）。
"""

from __future__ import annotations

from typing import Any

from curl_cffi import requests

from services.config import config
from utils.log import logger

# cf_clearance 需要同时挂在 auth.openai.com 与 chatgpt.com 两个域上
CLEARANCE_DOMAINS = (".openai.com", ".chatgpt.com")


def get_settings() -> dict[str, Any]:
    return config.get_flaresolverr_settings()


def is_enabled() -> bool:
    settings = get_settings()
    return bool(settings.get("enabled")) and bool(str(settings.get("endpoint") or "").strip())


def is_cloudflare_challenge(resp: Any) -> bool:
    """判断响应是否为 Cloudflare 浏览器质询（盾页）。"""
    if resp is None:
        return False
    try:
        text = str(getattr(resp, "text", "") or "").lower()
    except Exception:
        text = ""
    headers = getattr(resp, "headers", {}) or {}
    server = str(headers.get("server") or "").lower()
    return (
        "cloudflare" in server
        or "challenges.cloudflare.com" in text
        or "<title>just a moment" in text
        or "just a moment..." in text
        or "__cf_chl" in text
    )


def solve(url: str, proxy: str = "") -> dict[str, Any] | None:
    """调用 FlareSolverr 过盾。

    返回 ``{"cookies": {name: value, ...}, "user_agent": str}``；失败返回 ``None``。
    """
    settings = get_settings()
    endpoint = str(settings.get("endpoint") or "").strip()
    if not endpoint:
        logger.warning("[flaresolverr] 未配置 endpoint，跳过过盾")
        return None

    payload: dict[str, Any] = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": int(settings.get("solve_timeout_ms") or 60000),
    }

    # cf_clearance 绑定出口 IP：默认透传本服务 proxy，让 FlareSolverr 走同一出口
    use_proxy = str(proxy or "").strip()
    if not use_proxy and settings.get("use_app_proxy", True):
        use_proxy = config.get_proxy_settings()
    if use_proxy:
        payload["proxy"] = {"url": use_proxy}

    try:
        resp = requests.post(
            endpoint,
            json=payload,
            timeout=float(settings.get("request_timeout_secs") or 90),
        )
    except Exception as exc:
        logger.warning(f"[flaresolverr] 请求 FlareSolverr 失败: {exc}")
        return None

    try:
        data = resp.json()
    except Exception:
        body = str(getattr(resp, "text", "") or "")[:200]
        logger.warning(f"[flaresolverr] FlareSolverr 响应非 JSON: {body}")
        return None

    if str(data.get("status")) != "ok":
        logger.warning(f"[flaresolverr] 过盾失败: {data.get('message') or data}")
        return None

    solution = data.get("solution") or {}
    cookies: dict[str, str] = {}
    for cookie in solution.get("cookies") or []:
        name = str(cookie.get("name") or "").strip()
        if name:
            cookies[name] = str(cookie.get("value") or "")
    user_agent = str(solution.get("userAgent") or "").strip()

    if "cf_clearance" not in cookies:
        logger.warning(
            "[flaresolverr] FlareSolverr 未返回 cf_clearance（可能未触发质询或出口 IP 不一致）"
        )
        return None

    logger.info("[flaresolverr] 过盾成功，已获取 cf_clearance")
    return {"cookies": cookies, "user_agent": user_agent}


def apply_to_session(session: Any, solution: dict[str, Any], domains=CLEARANCE_DOMAINS) -> str:
    """把过盾得到的 cookie 注入 curl_cffi session，返回应改用的 User-Agent。"""
    cookies = (solution or {}).get("cookies") or {}
    for name, value in cookies.items():
        for domain in domains:
            try:
                session.cookies.set(name, value, domain=domain)
            except Exception:
                pass
    return str((solution or {}).get("user_agent") or "")


def solve_and_apply(session: Any, url: str, proxy: str = "") -> str | None:
    """过盾并把 cookie 注入 session。

    成功返回应改用的 User-Agent（调用方需把后续请求都换成该 UA）；
    未启用或失败返回 ``None``。
    """
    if not is_enabled():
        return None
    solution = solve(url, proxy=proxy)
    if not solution:
        return None
    user_agent = apply_to_session(session, solution)
    logger.info("[flaresolverr] cf_clearance 已注入 session，准备携带过盾结果重试")
    return user_agent or None
