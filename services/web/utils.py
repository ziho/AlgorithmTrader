"""
Web UI 辅助工具

提供 URL 解析和候选地址扩展等通用方法。
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from urllib.parse import urlparse, urlunparse

from nicegui import ui

_logger = logging.getLogger(__name__)


class _SafeTimer:
    """轻量安全定时器，避免页面切换后定时器空转。"""

    def __init__(self, interval: float, callback: Callable, *, once: bool = False):
        import asyncio
        from nicegui import background_tasks, context as nicegui_context
        from nicegui.client import Client

        self.interval = interval
        self.callback = callback
        self.once = once
        self.active = True
        self._cancelled = False

        self._client = nicegui_context.client
        self._slot = nicegui_context.slot

        async def _invoke():
            try:
                with self._slot:
                    result = self.callback()
                    if asyncio.iscoroutine(result):
                        await result
            except RuntimeError as exc:
                if "parent slot" in str(exc) or "has been deleted" in str(exc):
                    self.deactivate()
                    self._cancelled = True
                    return
                _logger.exception("timer callback error: %s", exc)
            except Exception as exc:
                _logger.exception("timer callback error: %s", exc)

        async def _can_start() -> bool:
            try:
                await self._client.connected()
                return True
            except Exception:
                return False

        def _slot_alive() -> bool:
            try:
                _ = self._slot.parent
                return True
            except Exception:
                return False

        def _client_alive() -> bool:
            return self._client.id in Client.instances

        def _should_stop() -> bool:
            return self._cancelled or (not _slot_alive()) or (not _client_alive())

        async def _run_once():
            if not await _can_start():
                return
            await asyncio.sleep(self.interval)
            if not _should_stop() and self.active:
                await _invoke()

        async def _run_loop():
            if not await _can_start():
                return
            while not _should_stop():
                start = asyncio.get_event_loop().time()
                if self.active:
                    await _invoke()
                dt = asyncio.get_event_loop().time() - start
                await asyncio.sleep(max(0.0, self.interval - dt))

        coroutine = _run_once if self.once else _run_loop
        self._task = background_tasks.create(coroutine(), name=str(callback))

    def deactivate(self) -> None:
        self.active = False

    def activate(self) -> None:
        self.active = True

    def cancel(self) -> None:
        self._cancelled = True
        if self._task:
            self._task.cancel()


def _wrap_safe_callback(callback: Callable, deactivate: Callable[[], None]) -> Callable:
    """包装 timer 回调，捕获 parent slot 已删除等异常，避免 CPU 空转。"""

    @functools.wraps(callback)
    async def _wrapper(*args, **kwargs):
        try:
            import asyncio
            result = callback(*args, **kwargs)
            if asyncio.iscoroutine(result):
                await result
        except RuntimeError as exc:
            if "parent slot" in str(exc) or "has been deleted" in str(exc):
                # parent element 已被删除（页面导航后），停止 timer，避免持续空转
                deactivate()
                return
            _logger.exception("timer callback error: %s", exc)
        except Exception as exc:
            _logger.exception("timer callback error: %s", exc)

    return _wrapper


def safe_timer(
    interval: float,
    callback: Callable,
    *,
    once: bool = False,
) -> ui.timer | _SafeTimer:
    """创建安全的 ``ui.timer``，自动在客户端断开时停用。

    NiceGUI 的 ``ui.timer`` 在页面导航后仍继续运行，但其 parent element
    已被删除，导致大量 ``RuntimeError: The parent slot of the element has
    been deleted.`` 错误。

    修复方式:
    1. 使用 client-scoped ``on_disconnect`` 仅关联当前客户端（不污染全局）
    2. 包装回调，捕获 parent_slot 异常，避免 CPU 空转
    3. 用 ``active=False`` 安全关闭
    """
    from nicegui import context as nicegui_context

    try:
        _ = nicegui_context.slot
    except Exception:
        timer_ref: ui.timer | None = None

        def _deactivate():
            if timer_ref is not None:
                timer_ref.active = False

        wrapped = _wrap_safe_callback(callback, _deactivate)
        timer_ref = ui.timer(interval, wrapped, once=once)
        return timer_ref

    return _SafeTimer(interval, callback, once=once)


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
