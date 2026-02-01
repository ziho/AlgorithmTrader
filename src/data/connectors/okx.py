"""
OKX 数据连接器

使用 ccxt 库接入 OKX 交易所:
- 拉取 OHLCV (K线) - 公开数据，无需 API key
- 拉取账户余额/持仓 - 需要 API key

注意:
- 公开数据接口 (K线/行情) 不需要认证
- 私有接口 (账户/下单) 需要 API key
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

import ccxt.async_support as ccxt
import pandas as pd

from src.core.config import get_settings
from src.core.instruments import Symbol
from src.core.timeframes import Timeframe


class OKXConnector:
    """
    OKX 交易所数据连接器

    支持:
    - 公开数据: OHLCV K线, 交易对信息
    - 私有数据: 账户余额, 持仓 (需要 API key)
    """

    def __init__(self, sandbox: bool | None = None) -> None:
        """
        初始化连接器

        Args:
            sandbox: 是否使用模拟盘，默认从配置读取
        """
        settings = get_settings()

        # 确定是否使用沙盒
        use_sandbox = sandbox if sandbox is not None else settings.okx.sandbox

        # 基础配置（公开接口不需要 API key）
        self._config: dict[str, Any] = {
            "enableRateLimit": True,
            "sandbox": use_sandbox,
            "options": {
                "defaultType": "spot",
            },
        }

        # 如果有 API key，添加认证信息
        api_key = settings.okx.api_key.get_secret_value()
        if api_key:
            self._config.update(
                {
                    "apiKey": api_key,
                    "secret": settings.okx.api_secret.get_secret_value(),
                    "password": settings.okx.passphrase.get_secret_value(),
                }
            )
            self._authenticated = True
        else:
            self._authenticated = False

        self._exchange: ccxt.okx | None = None

    async def _get_exchange(self) -> ccxt.okx:
        """获取或创建交易所实例"""
        if self._exchange is None:
            self._exchange = ccxt.okx(self._config)
        return self._exchange

    async def close(self) -> None:
        """关闭连接"""
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None

    async def __aenter__(self) -> "OKXConnector":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # ============================================
    # 公开数据接口 (无需 API key)
    # ============================================

    async def fetch_ohlcv(
        self,
        symbol: Symbol | str,
        timeframe: Timeframe | str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        """
        拉取 K 线数据

        Args:
            symbol: 交易对 (Symbol 对象或 CCXT 格式字符串如 "BTC/USDT")
            timeframe: 时间框架
            since: 开始时间
            limit: 数量限制 (最大 100)

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        exchange = await self._get_exchange()

        # 转换 symbol
        ccxt_symbol = symbol.ccxt if isinstance(symbol, Symbol) else symbol

        # 转换 timeframe
        tf_str = timeframe.to_ccxt() if isinstance(timeframe, Timeframe) else timeframe

        # 转换时间
        since_ts = int(since.timestamp() * 1000) if since else None

        # 拉取数据
        ohlcv = await exchange.fetch_ohlcv(
            symbol=ccxt_symbol,
            timeframe=tf_str,
            since=since_ts,
            limit=limit,
        )

        # 转换为 DataFrame
        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )

        # 转换时间戳
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

        # 转换为 Decimal 精度
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].apply(
                lambda x: Decimal(str(x)) if pd.notna(x) else Decimal("0")
            )

        return df

    async def fetch_ticker(self, symbol: Symbol | str) -> dict[str, Any]:
        """
        拉取最新行情

        Args:
            symbol: 交易对

        Returns:
            Ticker 信息
        """
        exchange = await self._get_exchange()

        ccxt_symbol = symbol.ccxt if isinstance(symbol, Symbol) else symbol

        return await exchange.fetch_ticker(ccxt_symbol)

    async def fetch_markets(self) -> list[dict[str, Any]]:
        """
        拉取所有交易对信息

        Returns:
            交易对列表
        """
        exchange = await self._get_exchange()
        await exchange.load_markets()
        return list(exchange.markets.values())

    # ============================================
    # 私有数据接口 (需要 API key)
    # ============================================

    def _require_auth(self) -> None:
        """检查是否已认证"""
        if not self._authenticated:
            raise RuntimeError(
                "此操作需要 API key。请在 .env 文件中配置 OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE"
            )

    async def fetch_balance(self) -> dict[str, Any]:
        """
        拉取账户余额

        Returns:
            余额信息

        Raises:
            RuntimeError: 未配置 API key
        """
        self._require_auth()
        exchange = await self._get_exchange()
        return await exchange.fetch_balance()

    async def fetch_positions(self) -> list[dict[str, Any]]:
        """
        拉取持仓信息

        Returns:
            持仓列表

        Raises:
            RuntimeError: 未配置 API key
        """
        self._require_auth()
        exchange = await self._get_exchange()
        return await exchange.fetch_positions()

    # ============================================
    # 资金费率接口 (公开数据)
    # ============================================

    async def fetch_funding_rate(self, symbol: Symbol | str) -> dict[str, Any]:
        """
        拉取当前资金费率

        Args:
            symbol: 交易对 (永续合约)

        Returns:
            资金费率信息，包含:
            - symbol: 交易对
            - fundingRate: 当前资金费率
            - fundingTimestamp: 下次结算时间
            - datetime: ISO 时间字符串
        """
        exchange = await self._get_exchange()

        # 转换为永续合约格式
        if isinstance(symbol, Symbol):
            ccxt_symbol = f"{symbol.base}/{symbol.quote}:{symbol.quote}"
        else:
            # 确保是永续格式
            if ":" not in symbol:
                base = symbol.replace("/USDT", "").replace("-USDT", "")
                ccxt_symbol = f"{base}/USDT:USDT"
            else:
                ccxt_symbol = symbol

        return await exchange.fetch_funding_rate(ccxt_symbol)

    async def fetch_funding_rate_history(
        self,
        symbol: Symbol | str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        """
        拉取资金费率历史

        Args:
            symbol: 交易对 (永续合约)
            since: 开始时间
            limit: 数量限制

        Returns:
            DataFrame with columns: timestamp, symbol, funding_rate
        """
        exchange = await self._get_exchange()

        # 转换为永续合约格式
        if isinstance(symbol, Symbol):
            ccxt_symbol = f"{symbol.base}/{symbol.quote}:{symbol.quote}"
        else:
            if ":" not in symbol:
                base = symbol.replace("/USDT", "").replace("-USDT", "")
                ccxt_symbol = f"{base}/USDT:USDT"
            else:
                ccxt_symbol = symbol

        # 转换时间
        since_ts = int(since.timestamp() * 1000) if since else None

        # 拉取数据
        funding_history = await exchange.fetch_funding_rate_history(
            symbol=ccxt_symbol,
            since=since_ts,
            limit=limit,
        )

        if not funding_history:
            return pd.DataFrame(columns=["timestamp", "symbol", "funding_rate"])

        # 转换为 DataFrame
        records = []
        for item in funding_history:
            records.append({
                "timestamp": pd.to_datetime(item.get("timestamp"), unit="ms", utc=True),
                "symbol": item.get("symbol", ccxt_symbol),
                "funding_rate": Decimal(str(item.get("fundingRate", 0) or 0)),
            })

        df = pd.DataFrame(records)
        return df


# 便捷函数
async def fetch_ohlcv_simple(
    symbol: str = "BTC/USDT",
    timeframe: str = "15m",
    limit: int = 100,
) -> pd.DataFrame:
    """
    简单拉取 K 线数据（用于快速测试）

    Args:
        symbol: 交易对，如 "BTC/USDT"
        timeframe: 时间框架，如 "15m"
        limit: 数量

    Returns:
        OHLCV DataFrame
    """
    async with OKXConnector() as connector:
        return await connector.fetch_ohlcv(symbol, timeframe, limit=limit)


async def fetch_funding_rate_simple(symbol: str = "BTC/USDT") -> dict[str, Any]:
    """
    简单拉取资金费率（用于快速测试）

    Args:
        symbol: 交易对

    Returns:
        资金费率信息
    """
    async with OKXConnector() as connector:
        return await connector.fetch_funding_rate(symbol)


# 导出
__all__ = [
    "OKXConnector",
    "fetch_ohlcv_simple",
    "fetch_funding_rate_simple",
]
