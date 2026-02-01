"""
InfluxDB Store - 实时数据存储与监控指标

职责:
- 写入最新 OHLCV 数据（用于 Grafana 实时监控）
- 存储交易指标、风控指标
- 存储回测结果摘要

数据模型:
- Measurement: ohlcv, trades, signals, metrics
- Tags: exchange, symbol, timeframe
- Fields: open, high, low, close, volume, etc.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import ASYNCHRONOUS, SYNCHRONOUS

from src.core.config import get_settings
from src.core.instruments import Symbol
from src.core.timeframes import Timeframe
from src.ops.logging import get_logger

logger = get_logger(__name__)


class InfluxStore:
    """InfluxDB 实时数据存储"""

    # 默认保留策略（天）
    DEFAULT_RETENTION_DAYS = 90

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        org: str | None = None,
        bucket: str | None = None,
        async_write: bool = True,
    ):
        """
        初始化 InfluxDB Store

        Args:
            url: InfluxDB URL
            token: 认证 Token
            org: 组织名称
            bucket: 存储桶名称
            async_write: 是否异步写入
        """
        settings = get_settings()

        self.url = url or settings.influxdb.url
        self.token = token or settings.influxdb.token.get_secret_value()
        self.org = org or settings.influxdb.org
        self.bucket = bucket or settings.influxdb.bucket

        # 创建客户端
        self._client = InfluxDBClient(
            url=self.url,
            token=self.token,
            org=self.org,
        )

        # 写入 API（支持同步和异步）
        write_options = ASYNCHRONOUS if async_write else SYNCHRONOUS
        self._write_api = self._client.write_api(write_options=write_options)

        # 查询 API
        self._query_api = self._client.query_api()

        logger.info(
            "influx_store_initialized",
            url=self.url,
            org=self.org,
            bucket=self.bucket,
            async_write=async_write,
        )

    def write_ohlcv(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        df: pd.DataFrame,
    ) -> int:
        """
        写入 OHLCV 数据

        Args:
            symbol: 交易对
            timeframe: 时间框架
            df: OHLCV DataFrame，需包含 timestamp, open, high, low, close, volume

        Returns:
            写入的点数
        """
        if df.empty:
            return 0

        points = []

        for _, row in df.iterrows():
            # 处理时间戳
            ts = row["timestamp"]
            if isinstance(ts, pd.Timestamp):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            # 构建数据点
            point = (
                Point("ohlcv")
                .tag("exchange", symbol.exchange.value)
                .tag("symbol", f"{symbol.base}/{symbol.quote}")
                .tag("timeframe", timeframe.value)
                .field("open", float(row["open"]))
                .field("high", float(row["high"]))
                .field("low", float(row["low"]))
                .field("close", float(row["close"]))
                .field("volume", float(row["volume"]))
                .time(ts, WritePrecision.S)
            )
            points.append(point)

        # 批量写入
        self._write_api.write(bucket=self.bucket, record=points)

        logger.debug(
            "influx_ohlcv_written",
            symbol=str(symbol),
            timeframe=timeframe.value,
            points=len(points),
        )

        return len(points)

    def write_bar(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        timestamp: datetime,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ):
        """
        写入单根 K 线

        Args:
            symbol: 交易对
            timeframe: 时间框架
            timestamp: 时间戳
            open_: 开盘价
            high: 最高价
            low: 最低价
            close: 收盘价
            volume: 成交量
        """
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        point = (
            Point("ohlcv")
            .tag("exchange", symbol.exchange.value)
            .tag("symbol", f"{symbol.base}/{symbol.quote}")
            .tag("timeframe", timeframe.value)
            .field("open", float(open_))
            .field("high", float(high))
            .field("low", float(low))
            .field("close", float(close))
            .field("volume", float(volume))
            .time(timestamp, WritePrecision.S)
        )

        self._write_api.write(bucket=self.bucket, record=point)

    def write_metric(
        self,
        measurement: str,
        tags: dict[str, str],
        fields: dict[str, float | int | str | bool],
        timestamp: datetime | None = None,
    ):
        """
        写入通用指标

        Args:
            measurement: 测量名称
            tags: 标签
            fields: 字段值
            timestamp: 时间戳，默认为当前时间
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        point = Point(measurement)

        for key, value in tags.items():
            point = point.tag(key, value)

        for key, value in fields.items():
            if isinstance(value, Decimal):
                value = float(value)
            point = point.field(key, value)

        point = point.time(timestamp, WritePrecision.S)

        self._write_api.write(bucket=self.bucket, record=point)

    def write_trade_signal(
        self,
        symbol: Symbol,
        signal_type: str,  # "buy", "sell", "close"
        price: float,
        quantity: float,
        strategy: str,
        reason: str | None = None,
        timestamp: datetime | None = None,
    ):
        """
        写入交易信号

        Args:
            symbol: 交易对
            signal_type: 信号类型
            price: 价格
            quantity: 数量
            strategy: 策略名称
            reason: 信号原因
            timestamp: 时间戳
        """
        tags = {
            "exchange": symbol.exchange.value,
            "symbol": f"{symbol.base}/{symbol.quote}",
            "signal_type": signal_type,
            "strategy": strategy,
        }

        fields: dict[str, float | int | str | bool] = {
            "price": float(price),
            "quantity": float(quantity),
        }
        if reason:
            fields["reason"] = reason

        self.write_metric("signals", tags, fields, timestamp)

    def write_risk_metric(
        self,
        metric_name: str,
        value: float,
        symbol: Symbol | None = None,
        strategy: str | None = None,
        timestamp: datetime | None = None,
    ):
        """
        写入风控指标

        Args:
            metric_name: 指标名称（如 drawdown, leverage, exposure）
            value: 指标值
            symbol: 可选，交易对
            strategy: 可选，策略名称
            timestamp: 时间戳
        """
        tags: dict[str, str] = {"metric": metric_name}

        if symbol:
            tags["exchange"] = symbol.exchange.value
            tags["symbol"] = f"{symbol.base}/{symbol.quote}"

        if strategy:
            tags["strategy"] = strategy

        fields: dict[str, float | int | str | bool] = {"value": float(value)}

        self.write_metric("risk_metrics", tags, fields, timestamp)

    def write_funding_rate(
        self,
        symbol: Symbol,
        funding_rate: float,
        funding_timestamp: datetime | None = None,
        next_funding_time: datetime | None = None,
    ):
        """
        写入资金费率

        Args:
            symbol: 交易对 (永续合约)
            funding_rate: 资金费率
            funding_timestamp: 费率时间戳
            next_funding_time: 下次结算时间
        """
        if funding_timestamp is None:
            funding_timestamp = datetime.now(UTC)
        elif funding_timestamp.tzinfo is None:
            funding_timestamp = funding_timestamp.replace(tzinfo=UTC)

        point = (
            Point("funding_rates")
            .tag("exchange", symbol.exchange.value)
            .tag("symbol", f"{symbol.base}/{symbol.quote}")
            .field("funding_rate", float(funding_rate))
        )

        if next_funding_time:
            point = point.field("next_funding_time", next_funding_time.isoformat())

        point = point.time(funding_timestamp, WritePrecision.S)

        self._write_api.write(bucket=self.bucket, record=point)

        logger.debug(
            "influx_funding_rate_written",
            symbol=str(symbol),
            funding_rate=funding_rate,
        )

    def write_funding_rates_batch(
        self,
        symbol: Symbol,
        df: pd.DataFrame,
    ) -> int:
        """
        批量写入资金费率历史

        Args:
            symbol: 交易对
            df: DataFrame with columns: timestamp, funding_rate

        Returns:
            写入的点数
        """
        if df.empty:
            return 0

        points = []

        for _, row in df.iterrows():
            ts = row["timestamp"]
            if isinstance(ts, pd.Timestamp):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            point = (
                Point("funding_rates")
                .tag("exchange", symbol.exchange.value)
                .tag("symbol", f"{symbol.base}/{symbol.quote}")
                .field("funding_rate", float(row["funding_rate"]))
                .time(ts, WritePrecision.S)
            )
            points.append(point)

        self._write_api.write(bucket=self.bucket, record=points)

        logger.debug(
            "influx_funding_rates_batch_written",
            symbol=str(symbol),
            points=len(points),
        )

        return len(points)

    def query_ohlcv(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start: datetime,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """
        查询 OHLCV 数据

        Args:
            symbol: 交易对
            timeframe: 时间框架
            start: 开始时间
            end: 结束时间，默认为当前时间

        Returns:
            OHLCV DataFrame
        """
        if end is None:
            end = datetime.now(UTC)

        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)

        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: {start.isoformat()}, stop: {end.isoformat()})
            |> filter(fn: (r) => r["_measurement"] == "ohlcv")
            |> filter(fn: (r) => r["exchange"] == "{symbol.exchange.value}")
            |> filter(fn: (r) => r["symbol"] == "{symbol.base}/{symbol.quote}")
            |> filter(fn: (r) => r["timeframe"] == "{timeframe.value}")
            |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
            |> sort(columns: ["_time"])
        '''

        try:
            result = self._query_api.query_data_frame(query)

            if result.empty:
                return pd.DataFrame(
                    columns=["timestamp", "open", "high", "low", "close", "volume"]
                )

            # 重命名列
            result = result.rename(columns={"_time": "timestamp"})

            # 选择需要的列
            cols = ["timestamp", "open", "high", "low", "close", "volume"]
            available_cols = [c for c in cols if c in result.columns]
            result = result[available_cols]

            return result

        except Exception as e:
            logger.error(
                "influx_query_failed",
                error=str(e),
                symbol=str(symbol),
            )
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

    def query_latest_bar(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
    ) -> dict[str, Any] | None:
        """
        查询最新一根 K 线

        Args:
            symbol: 交易对
            timeframe: 时间框架

        Returns:
            最新 K 线数据或 None
        """
        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: -7d)
            |> filter(fn: (r) => r["_measurement"] == "ohlcv")
            |> filter(fn: (r) => r["exchange"] == "{symbol.exchange.value}")
            |> filter(fn: (r) => r["symbol"] == "{symbol.base}/{symbol.quote}")
            |> filter(fn: (r) => r["timeframe"] == "{timeframe.value}")
            |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
            |> sort(columns: ["_time"], desc: true)
            |> limit(n: 1)
        '''

        try:
            result = self._query_api.query_data_frame(query)

            if result.empty:
                return None

            row = result.iloc[0]
            return {
                "timestamp": row["_time"],
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
            }

        except Exception as e:
            logger.error(
                "influx_query_latest_failed",
                error=str(e),
                symbol=str(symbol),
            )
            return None

    def health_check(self) -> bool:
        """
        检查 InfluxDB 连接状态

        Returns:
            是否健康
        """
        try:
            health = self._client.health()
            return health.status == "pass"
        except Exception as e:
            logger.error("influx_health_check_failed", error=str(e))
            return False

    def write_backtest_summary(self, summary: Any) -> None:
        """
        写入回测摘要

        Args:
            summary: BacktestSummary 对象
        """
        from datetime import UTC

        timestamp = summary.run_timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        point = (
            Point("backtest_summary")
            .tag("run_id", summary.run_id)
            .tag("strategy", summary.strategy_name)
            .tag("timeframe", summary.timeframe)
            .field("initial_capital", float(summary.initial_capital))
            .field("final_equity", float(summary.final_equity))
            .field("total_pnl", float(summary.total_pnl))
            .field("total_return", float(summary.total_return))
            .field("sharpe_ratio", float(summary.metrics.sharpe_ratio))
            .field("sortino_ratio", float(summary.metrics.sortino_ratio))
            .field("calmar_ratio", float(summary.metrics.calmar_ratio))
            .field("max_drawdown", float(summary.metrics.max_drawdown))
            .field("volatility", float(summary.metrics.volatility))
            .field("annualized_return", float(summary.metrics.annualized_return))
            .field("total_trades", summary.metrics.trade_stats.total_trades)
            .field("win_rate", summary.metrics.trade_stats.win_rate)
            .time(timestamp, WritePrecision.S)
        )

        self._write_api.write(bucket=self.bucket, record=point)
        logger.debug("influx_backtest_summary_written", run_id=summary.run_id)

    def write_backtest_equity(
        self,
        run_id: str,
        equity_curve: list[Any],
        sample_rate: int = 1,
    ) -> int:
        """
        写入回测权益曲线

        Args:
            run_id: 回测运行ID
            equity_curve: EquityPoint 列表
            sample_rate: 采样率（每N个点写入1个）

        Returns:
            写入的点数
        """
        if not equity_curve:
            return 0

        points = []
        for i, ep in enumerate(equity_curve):
            if i % sample_rate != 0:
                continue

            ts = ep.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            point = (
                Point("backtest_equity")
                .tag("run_id", run_id)
                .field("equity", float(ep.equity))
                .field("cash", float(ep.cash))
                .field("position_value", float(ep.position_value))
                .field("drawdown", float(ep.drawdown))
                .field("drawdown_pct", float(ep.drawdown_pct))
                .time(ts, WritePrecision.S)
            )
            points.append(point)

        if points:
            self._write_api.write(bucket=self.bucket, record=points)
            logger.debug(
                "influx_backtest_equity_written",
                run_id=run_id,
                points=len(points),
            )

        return len(points)

    def flush(self):
        """刷新写入缓冲区"""
        self._write_api.flush()

    def close(self):
        """关闭连接"""
        self._write_api.close()
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
