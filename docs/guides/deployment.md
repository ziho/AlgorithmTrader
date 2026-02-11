# 部署指南

本指南介绍如何将 AlgorithmTrader 部署到生产环境。

## 部署架构

### 推荐配置

| 组件 | 配置 | 说明 |
|------|------|------|
| CPU | 12代 i5 或更高 | 4核8线程以上 |
| 内存 | 64GB | 最低 16GB |
| 硬盘 | 500GB SSD | 用于数据存储 |
| 系统 | Ubuntu 22.04 LTS | 24小时运行 |
| 网络 | 稳定网络 | 低延迟到交易所 |

### 部署方式

```
┌─────────────────────────────────────────┐
│           Docker Compose                │
├─────────────────────────────────────────┤
│  InfluxDB  │  Grafana  │  Loki          │
│  collector │  trader   │  scheduler     │
│  notifier  │  web      │  backtest      │
└─────────────────────────────────────────┘
         ↓
   宿主机文件系统
   - /data/parquet    (历史数据)
   - /data/influxdb   (时序数据)
   - /logs            (日志文件)
```

## 环境准备

### 1. 系统更新

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装必要工具
sudo apt install -y git curl wget vim htop
```

### 2. 安装 Docker

```bash
# 安装 Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 添加当前用户到 docker 组
sudo usermod -aG docker $USER

# 重新登录使权限生效
newgrp docker

# 验证安装
docker --version
docker-compose --version
```

### 3. 配置系统限制

编辑 `/etc/sysctl.conf`:

```bash
# 增加文件句柄限制
fs.file-max = 2097152

# 优化网络
net.core.somaxconn = 32768
net.ipv4.tcp_max_syn_backlog = 8192
```

应用配置：

```bash
sudo sysctl -p
```

编辑 `/etc/security/limits.conf`:

```
* soft nofile 1000000
* hard nofile 1000000
```

## 部署步骤

### 1. 克隆项目

```bash
cd /opt
sudo git clone https://github.com/ziho/AlgorithmTrader.git
sudo chown -R $USER:$USER AlgorithmTrader
cd AlgorithmTrader
```

### 2. 配置环境变量

```bash
cp .env.example .env
vim .env
```

关键配置项：

```bash
# 环境
ENVIRONMENT=production

# OKX API
OKX_API_KEY=your_api_key
OKX_API_SECRET=your_api_secret
OKX_PASSPHRASE=your_passphrase

# Telegram 通知
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# InfluxDB
INFLUXDB_URL=http://influxdb:8086
INFLUXDB_TOKEN=your_production_token
INFLUXDB_ORG=algorithmtrader
INFLUXDB_BUCKET=trading

# 数据路径
DATA_PATH=/opt/AlgorithmTrader/data
LOG_PATH=/opt/AlgorithmTrader/logs
```

### 3. 创建数据目录

```bash
mkdir -p data/parquet/okx
mkdir -p data/influxdb
mkdir -p logs
mkdir -p backtest_reports
```

### 4. 构建和启动服务

```bash
# 构建镜像（首次或代码更新后）
docker-compose build

# 启动所有服务
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f
```

## 服务配置

### InfluxDB 初始化

访问 http://your-server:8086 完成初始化：

1. 设置用户名和密码
2. 创建组织: `algorithmtrader`
3. 创建 bucket: `trading`
4. 生成 API Token 并更新到 `.env`

### Grafana 配置

访问 http://your-server:3000:

1. 登录（admin / algorithmtrader123）
2. 添加 InfluxDB 数据源
3. 导入监控面板:
   - `infra/grafana/dashboards/backtest.json`
   - `infra/grafana/dashboards/live_trading.json`
   - `infra/grafana/dashboards/system_monitor.json`

### Web 管理界面

访问 http://your-server:8080

- 策略管理
- 回测任务
- 系统状态

## 数据采集

### 历史数据初始化

```bash
# 采集最近一年的数据
docker-compose exec collector python /app/scripts/demo_collect.py \
    --symbol BTC/USDT ETH/USDT SOL/USDT \
    --days 365 \
    --timeframe 1h
```

### 自动化采集

`collector` 服务会自动定时采集数据，配置在 `services/collector/main.py`:

```python
# 每小时采集一次 1h K线
scheduler.add_job(
    collect_bars,
    trigger="cron",
    minute=2,  # 每小时的第 2 分钟
    args=["1h"]
)
```

## 监控与告警

### 系统监控

在 Grafana 中监控：

- **CPU/内存使用率**: 容器资源监控
- **磁盘空间**: 确保有足够空间
- **网络延迟**: 到交易所的延迟
- **数据采集状态**: 是否有缺失
- **错误率**: 异常和错误统计

### 告警配置

编辑 `infra/grafana/provisioning/alerting/rules.yaml`:

```yaml
groups:
  - name: trading_alerts
    interval: 1m
    rules:
      - alert: DataCollectionFailed
        expr: rate(data_collect_errors[5m]) > 0.1
        annotations:
          summary: "数据采集失败率过高"
          
      - alert: HighDrawdown
        expr: portfolio_drawdown > 0.15
        annotations:
          summary: "回撤超过 15%"
```

### Telegram 通知

系统会自动发送以下通知：

- 订单成交
- 触发风控
- 策略启停
- 数据异常
- 系统错误

## 备份策略

### 1. 数据备份

创建备份脚本 `scripts/backup.sh`:

```bash
#!/bin/bash

BACKUP_DIR="/backup/algorithmtrader"
DATE=$(date +%Y%m%d_%H%M%S)

# 备份 Parquet 数据
tar -czf "$BACKUP_DIR/parquet_$DATE.tar.gz" data/parquet/

# 备份 InfluxDB
docker-compose exec -T influxdb influx backup /backup/influxdb_$DATE

# 备份配置
tar -czf "$BACKUP_DIR/config_$DATE.tar.gz" .env config/

# 删除 30 天前的备份
find "$BACKUP_DIR" -type f -mtime +30 -delete
```

设置定时任务：

```bash
crontab -e

# 每天凌晨 2 点备份
0 2 * * * /opt/AlgorithmTrader/scripts/backup.sh >> /opt/AlgorithmTrader/logs/backup.log 2>&1
```

### 2. 恢复数据

```bash
# 恢复 Parquet
tar -xzf parquet_20260201_020000.tar.gz -C /opt/AlgorithmTrader/

# 恢复 InfluxDB
docker-compose exec influxdb influx restore /backup/influxdb_20260201_020000
```

## 日志管理

### 日志轮转

编辑 `docker-compose.yml` 中的 logging 配置：

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "50m"
    max-file: "10"
```

### 日志聚合 (Loki)

已配置 Loki + Promtail 收集容器日志：

```bash
# 查看日志
docker-compose logs -f loki promtail

# 在 Grafana 中查询
# Explore → Loki → {container_name="algorithmtrader-trader"}
```

## 安全加固

### 1. 防火墙配置

```bash
# 只开放必要端口
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 3000/tcp  # Grafana (可选，建议内网访问)
sudo ufw allow 8080/tcp  # Web 界面 (可选)
sudo ufw enable
```

### 2. API 密钥安全

- 不要将 `.env` 提交到 Git
- 使用只读 API 密钥（如果只做监控）
- 定期轮换密钥
- 限制 API 密钥的 IP 白名单

### 3. 容器安全

```bash
# 限制容器资源
docker-compose.yml:
  services:
    trader:
      mem_limit: 2g
      cpus: 2
```

## 性能优化

### 1. InfluxDB 优化

编辑 `infra/influxdb/influxdb.conf`:

```toml
[data]
cache-max-memory-size = "2g"
cache-snapshot-memory-size = "256m"

[coordinator]
write-timeout = "30s"
```

### 2. Docker 优化

编辑 `/etc/docker/daemon.json`:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
```

重启 Docker：

```bash
sudo systemctl restart docker
```

## 故障排查

### 服务无法启动

```bash
# 查看详细日志
docker-compose logs <service_name>

# 检查端口占用
sudo netstat -tulpn | grep :8086

# 重建容器
docker-compose down
docker-compose up -d --force-recreate
```

### 数据采集失败

```bash
# 检查网络连接
curl https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1H

# 检查 API 密钥
docker-compose exec collector env | grep OKX

# 查看采集日志
docker-compose logs collector | grep ERROR
```

### 磁盘空间不足

```bash
# 清理 Docker 资源
docker system prune -a

# 清理旧的 Parquet 文件
find data/parquet -type f -mtime +180 -delete

# 清理旧的回测报告
find backtest_reports -type f -mtime +90 -delete
```

## 升级部署

### 代码更新

```bash
cd /opt/AlgorithmTrader

# 拉取最新代码
git pull origin main

# 重建镜像
docker-compose build

# 重启服务
docker-compose down
docker-compose up -d

# 检查状态
docker-compose ps
```

### 数据库迁移

如果有数据库结构变更：

```bash
# 备份数据
./scripts/backup.sh

# 运行迁移脚本（如果有）
docker-compose exec trader python scripts/migrate.py
```

## 生产检查清单

部署前确认：

- [ ] `.env` 已正确配置所有密钥
- [ ] 防火墙已配置
- [ ] 备份脚本已设置定时任务
- [ ] Grafana 监控面板已导入
- [ ] Telegram 通知测试通过
- [ ] 历史数据已采集
- [ ] 回测验证策略有效性
- [ ] 风控参数已设置
- [ ] 磁盘空间充足（100GB+ 可用）
- [ ] 系统时间已同步（NTP）

## 下一步

- 阅读 [使用指南](user_guide.md) 了解核心流程
- 查看 [Web 界面](web_ui.md) 管理回测与服务状态
- 需要排查问题时参考 [FAQ](faq.md)
