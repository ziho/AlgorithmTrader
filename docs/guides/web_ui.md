# Web UI 使用指南

AlgorithmTrader 提供基于 NiceGUI 的 Web 管理界面，用于数据下载、回测、优化和服务状态查看。

## 启动与访问

```bash
docker compose --profile web up -d web
```

访问：

```
http://localhost:8080
```

---

## 页面功能概览

### Dashboard (首页)

- 服务状态（InfluxDB/Grafana/Collector/Trader 等）
- 数据采集概览与缺口检测
- 下载任务进度
- 回测与实盘概览
- 快捷入口（Grafana / InfluxDB / 数据管理）

### 数据管理 (/data)

- Binance 历史数据下载（data.binance.vision）
- 实时行情（Binance REST，3-5 秒刷新）
- 本地 Parquet 数据扫描与统计
- InfluxDB 同步

### A 股数据分析 (/a-share)

- 选股筛选（截面因子排名）
- 个股分析（K 线 + 因子时序）
- 全市场日线/基本面回填
- 本地数据统计与健康检查

### 策略管理 (/strategies)

- 策略列表与启用状态
- 参数配置与保存
- 运行状态与持仓概览

### 回测 (/backtests)

- 回测历史列表
- 新建回测任务
- 多回测对比
- 结果详情

### 优化 (/optimization)

- 参数空间配置
- 运行优化任务
- 结果对比

### 通知管理 (/notifications)

- Telegram（支持多 Bot）
- Bark（支持多设备）
- SMTP 邮件（预留配置）
- 通用 Webhook

### 设置 (/settings)

- 系统信息
- 环境变量概览
- 数据路径与状态

---

## 服务状态说明

| 状态 | 含义 |
|------|------|
| ✅ 正常 | 服务运行正常 |
| ⚠️ 警告 | 服务可能存在问题 |
| ❌ 异常 | 服务不可用 |
| ❓ 未知 | 服务未部署或无法检测 |

检测方式：
- InfluxDB / Grafana: HTTP 健康检查
- Collector / Trader / Scheduler / Notifier: 容器状态检测

---

## 通知配置示例

### Bark (iOS 推送)

```env
BARK_URLS=https://api.day.app/your-device-key
```

### 通用 Webhook

```env
WEBHOOK_URL=https://your-webhook-url.com/notify
```

---

## 常见问题

### 服务状态显示“未知”

```bash
docker compose ps
```

### 数据页面加载慢

Parquet 数据量较大时属于正常现象，可使用命令行工具查询。
