"""
Web UI 辅助工具

提供 URL 解析和候选地址扩展等通用方法。
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse, urlunparse

from nicegui import ui


def safe_timer(
    interval: float,
    callback: Callable,
    *,
    once: bool = False,
) -> ui.timer:
    """创建安全的 ``ui.timer``，自动在 parent slot 被销毁时停用。

    NiceGUI 的 ``ui.timer`` 在页面导航后仍继续运行，但其 parent element
    已被删除，导致大量 ``RuntimeError: The parent slot of the element has
    been deleted.`` 错误。此包装器在回调出现该异常时自动将 timer 停用。
    """

    timer_ref: ui.timer | None = None

    def _wrapper():
        try:
            result = callback()
            # 支持 async 回调
            return result
        except RuntimeError as exc:
            if "parent slot" in str(exc) and timer_ref is not None:
                timer_ref.active = False
            # 不再向上传播，避免日志洪泛
        except Exception:
            pass  # 其它异常由 NiceGUI 内部处理

    timer_ref = ui.timer(interval, _wrapper, once=once)
    return timer_ref


def _with_host(url: str, host: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme:
        return url
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def candidate_urls(url: str, service_host: str) -> list[str]:
    """
    生成用于连接探测的候选 URL 列表。

    - 当 URL 使用服务名(如 influxdb/grafana)时，追加 localhost/127.0.0.1 作为回退
    - 当 URL 使用 localhost/127.0.0.1 时，追加服务名作为回退
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    candidates: list[str] = [url]

    if hostname == service_host:
        candidates.append(_with_host(url, "localhost"))
        candidates.append(_with_host(url, "127.0.0.1"))
    elif hostname in ("localhost", "127.0.0.1"):
        candidates.append(_with_host(url, service_host))

    # 去重保持顺序
    seen: set[str] = set()
    deduped: list[str] = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped
