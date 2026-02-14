# 部署指南

本指南说明如何用 Docker Compose 部署 AlgorithmTrader。

## 推荐配置

| 组件 | 建议 | 说明 |
|------|------|------|
| CPU | 4 核以上 | 回测/下载并行时更稳 |
| 内存 | 16GB+ | A 股全市场数据建议 32GB+ |
| 硬盘 | SSD 500GB+ | 历史数据占用较大 |
| 系统 | Ubuntu 22.04 LTS | 7x24 运行 |

## 部署步骤

### 1. 安装 Docker

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

### 2. 克隆项目

```bash
cd /opt
sudo git clone https://github.com/ziho/AlgorithmTrader.git
sudo chown -R $USER:$USER AlgorithmTrader
cd AlgorithmTrader
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

常用配置项：

```dotenv
ENV=prod

OKX_API_KEY=
OKX_API_SECRET=
OKX_PASSPHRASE=
OKX_SIMULATED_TRADING=true

INFLUXDB_URL=http://influxdb:8086
INFLUXDB_TOKEN=algorithmtrader-dev-token
INFLUXDB_ORG=algorithmtrader
INFLUXDB_BUCKET=trading

DATA_DIR=./data
PARQUET_DIR=./data/parquet
LOG_DIR=./logs
```

### 4. 启动基础设施

```bash
docker compose up -d influxdb grafana
```

### 5. 启动服务（按需）

```bash
# 交易相关服务
docker compose --profile trading up -d collector trader scheduler notifier

# Web 管理界面
docker compose --profile web up -d web

# 数据下载相关
docker compose --profile data up -d data-fetcher realtime-sync
```

### 6. 验证

- Grafana: http://your-server:3000
- Web UI: http://your-server:8080
- InfluxDB: http://your-server:8086

---

## 常见维护

```bash
# 查看状态
docker compose ps

# 查看日志
docker compose logs -f web

# 重启服务
docker compose restart collector
```
