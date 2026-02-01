"""
配置设置定义

使用 Pydantic Settings 实现类型安全的配置
"""

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """运行环境"""

    DEV = "dev"
    PROD = "prod"


class OKXSettings(BaseSettings):
    """OKX 交易所配置"""

    model_config = SettingsConfigDict(env_prefix="OKX_")

    api_key: SecretStr = Field(default=SecretStr(""), description="OKX API Key")
    api_secret: SecretStr = Field(default=SecretStr(""), description="OKX API Secret")
    passphrase: SecretStr = Field(default=SecretStr(""), description="OKX Passphrase")
    sandbox: bool = Field(default=True, description="是否使用模拟盘")


class IBKRSettings(BaseSettings):
    """Interactive Brokers 配置"""

    model_config = SettingsConfigDict(env_prefix="IBKR_")

    host: str = Field(default="127.0.0.1", description="TWS/Gateway 地址")
    port: int = Field(default=7497, description="TWS/Gateway 端口")
    client_id: int = Field(default=1, description="客户端 ID")


class InfluxDBSettings(BaseSettings):
    """InfluxDB 配置"""

    model_config = SettingsConfigDict(env_prefix="INFLUXDB_")

    url: str = Field(default="http://localhost:8086", description="InfluxDB URL")
    token: SecretStr = Field(default=SecretStr(""), description="InfluxDB Token")
    org: str = Field(default="algorithmtrader", description="组织名称")
    bucket: str = Field(default="trading", description="默认 Bucket")


class TelegramSettings(BaseSettings):
    """Telegram 通知配置"""

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: SecretStr = Field(default=SecretStr(""), description="Bot Token")
    chat_id: str = Field(default="", description="Chat ID")

    @property
    def enabled(self) -> bool:
        """检查 Telegram 是否已配置"""
        return bool(self.bot_token.get_secret_value() and self.chat_id)


class WebhookSettings(BaseSettings):
    """Webhook 通知配置"""

    model_config = SettingsConfigDict(env_prefix="WEBHOOK_")

    url: str = Field(default="", description="Webhook URL (支持 Bark 或通用 Webhook)")

    @property
    def enabled(self) -> bool:
        """检查 Webhook 是否已配置"""
        return bool(self.url)


class Settings(BaseSettings):
    """主配置类"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 环境
    env: Environment = Field(default=Environment.DEV, description="运行环境")

    # 数据目录
    data_dir: Path = Field(default=Path("./data"), description="数据根目录")
    parquet_dir: Path = Field(
        default=Path("./data/parquet"), description="Parquet 目录"
    )
    log_dir: Path = Field(default=Path("./logs"), description="日志目录")

    # 日志
    log_level: str = Field(default="INFO", description="日志级别")

    # 调度
    bar_close_delay: int = Field(default=10, description="Bar close 触发延迟(秒)")

    # 子配置
    okx: OKXSettings = Field(default_factory=OKXSettings)
    ibkr: IBKRSettings = Field(default_factory=IBKRSettings)
    influxdb: InfluxDBSettings = Field(default_factory=InfluxDBSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    webhook: WebhookSettings = Field(default_factory=WebhookSettings)

    @property
    def is_prod(self) -> bool:
        """是否为生产环境"""
        return self.env == Environment.PROD

    @property
    def is_dev(self) -> bool:
        """是否为开发环境"""
        return self.env == Environment.DEV

    def ensure_dirs(self) -> None:
        """确保必要目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """
    获取配置单例

    使用 lru_cache 确保配置只加载一次

    Returns:
        Settings: 配置实例
    """
    return Settings()
