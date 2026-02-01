# Web UI 使用指南

AlgorithmTrader 提供了基于 NiceGUI 的 Web 管理界面，可在浏览器中管理所有功能。

## 访问 Web UI

启动服务后，访问：

```
http://localhost:8080
```

## 页面功能

### Dashboard (首页)

系统状态总览：

- **服务状态**: 显示各服务（InfluxDB、Grafana、Collector 等）的运行状态
  - 点击有链接的服务卡片可直接跳转到对应服务
- **快捷入口**: 一键访问 Grafana 监控面板和 InfluxDB 数据库
- **统计卡片**: 运行中的策略数、今日交易数等
- **最近告警**: 从日志中提取的最近错误和警告
- **最近回测**: 显示最近运行的回测结果
- **通知测试**: 测试 Bark/Webhook 通知是否正常

### 数据管理 (/data)

管理历史数据和实时同步：

**Parquet 数据**
- 查看所有已下载的历史数据
- 显示交易所、交易对、时间范围、数据量
- 缺口检测状态

**InfluxDB 数据**
- 检查 InfluxDB 连接状态
- 显示各交易对的数据点数
- 快速跳转到 InfluxDB UI

**数据下载**
- 选择交易所、交易对、时间框架
- 设置下载时间范围
- 实时显示下载进度和日志
- 支持多交易对批量下载

**实时同步**
- 配置实时同步的交易对
- 检查数据缺口
- 手动触发同步

### 策略管理 (/strategies)

策略配置和管理：

- 查看所有已注册的策略
- 启用/禁用策略
- 配置策略参数
- 查看策略运行状态

### 回测 (/backtests)

历史回测管理：

- 创建新回测任务
- 查看回测进度
- 浏览历史回测结果
- 下载回测报告

### 优化 (/optimization)

参数优化：

- 配置参数搜索空间
- 运行参数优化
- 查看优化结果

### 设置 (/settings)

系统配置：

**通知设置**
- 显示当前 Bark/Webhook 配置状态
- 配置说明和教程
- 发送测试通知

**数据库连接**
- InfluxDB 连接信息
- Grafana 连接信息
- 连接测试

**系统信息**
- Python 版本、操作系统信息
- 环境变量状态
- 数据统计

## 主题切换

点击右上角的主题按钮循环切换：
- 🌐 跟随系统
- ☀️ 亮色模式
- 🌙 暗色模式

## 服务状态说明

| 状态 | 含义 |
|------|------|
| ✅ 正常 | 服务运行正常 |
| ⚠️ 警告 | 服务可能存在问题 |
| ❌ 异常 | 服务不可用 |
| ❓ 未知 | 服务未部署或无法检测 |

服务状态通过以下方式检测：
- **InfluxDB/Grafana**: HTTP 健康端点检查
- **Collector/Trader/Scheduler/Notifier**: Docker 容器状态检查

## 配置通知

### Bark (iOS 推送)

1. 在 iOS 设备安装 [Bark App](https://apps.apple.com/app/bark/id1403753865)
2. 打开 App，复制设备推送地址
3. 在 `.env` 文件中配置：

```env
WEBHOOK_URL=https://api.day.app/your-device-key
```

4. 重启服务：

```bash
docker-compose down && docker-compose up -d
```

5. 在 Dashboard 或 Settings 页面点击"发送测试通知"验证

### 通用 Webhook

支持任何接受 POST JSON 的 Webhook 服务：

```env
WEBHOOK_URL=https://your-webhook-url.com/notify
```

请求格式：
```json
{
  "type": "system",
  "level": "info",
  "title": "通知标题",
  "content": "通知内容",
  "details": {},
  "timestamp": "2024-01-01T00:00:00+00:00"
}
```

## 快捷链接

Web UI 提供以下快捷入口：

| 服务 | URL | 说明 |
|------|-----|------|
| Web UI | http://localhost:8080 | 主管理界面 |
| Grafana | http://localhost:3000 | 监控面板 |
| InfluxDB | http://localhost:8086 | 时序数据库 |

## 常见问题

### 服务状态显示"未知"

可能原因：
1. 服务容器未启动
2. Docker 命令不可用（非容器内运行）

解决方法：
```bash
# 检查容器状态
docker-compose ps

# 启动所有服务
docker-compose up -d
```

### 通知测试失败

可能原因：
1. WEBHOOK_URL 未配置
2. URL 格式错误
3. 网络无法访问 Bark 服务器

解决方法：
1. 检查 `.env` 文件中的 WEBHOOK_URL
2. 确保 URL 格式正确（Bark: `https://api.day.app/your-key`）
3. 检查网络连接

### 数据页面加载慢

原因：需要扫描 Parquet 文件目录

解决方法：
- 数据量大时属正常现象
- 可以通过命令行工具查询数据
