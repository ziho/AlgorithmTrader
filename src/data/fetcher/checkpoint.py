"""
断点续传状态管理

使用 SQLite 记录下载进度，支持断点续传
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class CheckpointStore:
    """
    断点续传状态存储

    使用 SQLite 记录每个 (exchange, symbol, timeframe) 组合的下载进度
    """

    DB_NAME = "fetch_checkpoint.db"

    def __init__(self, data_dir: Path):
        """
        初始化状态存储

        Args:
            data_dir: 数据目录，状态文件存放在此目录下
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / self.DB_NAME

        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    day INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    checksum TEXT,
                    rows_count INTEGER DEFAULT 0,
                    file_size INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(exchange, symbol, timeframe, year, month, day)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS fetch_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    earliest_date TEXT,
                    latest_date TEXT,
                    total_rows INTEGER DEFAULT 0,
                    last_sync_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(exchange, symbol, timeframe)
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_progress_lookup
                ON download_progress(exchange, symbol, timeframe, status)
            """)

            conn.commit()

    def mark_completed(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
        day: int | None = None,
        rows_count: int = 0,
        file_size: int = 0,
        checksum: str | None = None,
    ) -> None:
        """
        标记某个时间段下载完成

        Args:
            exchange: 交易所
            symbol: 交易对
            timeframe: 时间框架
            year: 年份
            month: 月份
            day: 日期（可选，用于日级别数据）
            rows_count: 行数
            file_size: 文件大小
            checksum: 校验和
        """
        now = datetime.now(UTC).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO download_progress
                    (exchange, symbol, timeframe, year, month, day, status,
                     rows_count, file_size, checksum, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, symbol, timeframe, year, month, day)
                DO UPDATE SET
                    status = 'completed',
                    rows_count = excluded.rows_count,
                    file_size = excluded.file_size,
                    checksum = excluded.checksum,
                    error_message = NULL,
                    updated_at = excluded.updated_at
            """,
                (
                    exchange,
                    symbol,
                    timeframe,
                    year,
                    month,
                    day,
                    rows_count,
                    file_size,
                    checksum,
                    now,
                    now,
                ),
            )
            conn.commit()

    def mark_failed(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
        day: int | None = None,
        error_message: str = "",
    ) -> None:
        """标记下载失败"""
        now = datetime.now(UTC).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO download_progress
                    (exchange, symbol, timeframe, year, month, day, status,
                     error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'failed', ?, ?, ?)
                ON CONFLICT(exchange, symbol, timeframe, year, month, day)
                DO UPDATE SET
                    status = 'failed',
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
            """,
                (
                    exchange,
                    symbol,
                    timeframe,
                    year,
                    month,
                    day,
                    error_message,
                    now,
                    now,
                ),
            )
            conn.commit()

    def mark_pending(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
        day: int | None = None,
    ) -> None:
        """将已完成的记录重置为 pending（当 parquet 文件丢失时使用）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                DELETE FROM download_progress
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
                  AND year = ? AND month = ? AND day IS ?
            """,
                (exchange, symbol, timeframe, year, month, day),
            )
            conn.commit()

    def is_completed(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
        day: int | None = None,
    ) -> bool:
        """
        检查某个时间段是否已完成下载

        Args:
            exchange: 交易所
            symbol: 交易对
            timeframe: 时间框架
            year: 年份
            month: 月份
            day: 日期（可选）

        Returns:
            是否已完成
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT status FROM download_progress
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
                  AND year = ? AND month = ? AND (day = ? OR (day IS NULL AND ? IS NULL))
            """,
                (exchange, symbol, timeframe, year, month, day, day),
            )

            row = cursor.fetchone()
            return row is not None and row[0] == "completed"

    def get_completed_periods(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
    ) -> list[tuple[int, int, int | None]]:
        """
        获取已完成的时间段列表

        Returns:
            [(year, month, day), ...] 列表
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT year, month, day FROM download_progress
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
                  AND status = 'completed'
                ORDER BY year, month, day
            """,
                (exchange, symbol, timeframe),
            )

            return [(row[0], row[1], row[2]) for row in cursor.fetchall()]

    def get_pending_periods(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_year: int,
        start_month: int,
        end_year: int,
        end_month: int,
    ) -> list[tuple[int, int]]:
        """
        获取待下载的月份列表

        Args:
            exchange: 交易所
            symbol: 交易对
            timeframe: 时间框架
            start_year: 开始年
            start_month: 开始月
            end_year: 结束年
            end_month: 结束月

        Returns:
            [(year, month), ...] 待下载月份列表
        """
        completed = set()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT year, month FROM download_progress
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
                  AND status = 'completed' AND day IS NULL
            """,
                (exchange, symbol, timeframe),
            )

            for row in cursor.fetchall():
                completed.add((row[0], row[1]))

        # 生成所有需要的月份
        pending = []
        year, month = start_year, start_month

        while (year, month) <= (end_year, end_month):
            if (year, month) not in completed:
                pending.append((year, month))

            # 下一个月
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1

        return pending

    def update_metadata(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        earliest_date: datetime | None = None,
        latest_date: datetime | None = None,
        total_rows: int | None = None,
    ) -> None:
        """更新元数据"""
        now = datetime.now(UTC).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            # 先检查是否存在
            cursor = conn.execute(
                """
                SELECT id, earliest_date, latest_date, total_rows
                FROM fetch_metadata
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
            """,
                (exchange, symbol, timeframe),
            )

            row = cursor.fetchone()

            if row:
                # 更新
                updates = []
                params = []

                if earliest_date:
                    new_earliest = earliest_date.isoformat()
                    if not row[1] or new_earliest < row[1]:
                        updates.append("earliest_date = ?")
                        params.append(new_earliest)

                if latest_date:
                    new_latest = latest_date.isoformat()
                    if not row[2] or new_latest > row[2]:
                        updates.append("latest_date = ?")
                        params.append(new_latest)

                if total_rows is not None:
                    updates.append("total_rows = total_rows + ?")
                    params.append(total_rows)

                if updates:
                    updates.append("last_sync_at = ?")
                    params.append(now)
                    updates.append("updated_at = ?")
                    params.append(now)

                    params.extend([exchange, symbol, timeframe])

                    conn.execute(
                        f"""
                        UPDATE fetch_metadata
                        SET {", ".join(updates)}
                        WHERE exchange = ? AND symbol = ? AND timeframe = ?
                    """,
                        params,
                    )
            else:
                # 插入
                conn.execute(
                    """
                    INSERT INTO fetch_metadata
                        (exchange, symbol, timeframe, earliest_date, latest_date,
                         total_rows, last_sync_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        exchange,
                        symbol,
                        timeframe,
                        earliest_date.isoformat() if earliest_date else None,
                        latest_date.isoformat() if latest_date else None,
                        total_rows or 0,
                        now,
                        now,
                        now,
                    ),
                )

            conn.commit()

    def get_metadata(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
    ) -> dict | None:
        """获取元数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT earliest_date, latest_date, total_rows, last_sync_at
                FROM fetch_metadata
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
            """,
                (exchange, symbol, timeframe),
            )

            row = cursor.fetchone()
            if row:
                return {
                    "earliest_date": datetime.fromisoformat(row[0]) if row[0] else None,
                    "latest_date": datetime.fromisoformat(row[1]) if row[1] else None,
                    "total_rows": row[2],
                    "last_sync_at": datetime.fromisoformat(row[3]) if row[3] else None,
                }
            return None

    def reset(
        self,
        exchange: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> int:
        """
        重置下载状态（用于强制重新下载）

        Returns:
            删除的记录数
        """
        with sqlite3.connect(self.db_path) as conn:
            conditions = []
            params = []

            if exchange:
                conditions.append("exchange = ?")
                params.append(exchange)
            if symbol:
                conditions.append("symbol = ?")
                params.append(symbol)
            if timeframe:
                conditions.append("timeframe = ?")
                params.append(timeframe)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            cursor = conn.execute(
                f"DELETE FROM download_progress WHERE {where_clause}", params
            )
            deleted = cursor.rowcount
            conn.commit()

            return deleted
