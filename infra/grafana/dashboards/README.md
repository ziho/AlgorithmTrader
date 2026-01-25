# Grafana Dashboards

存放 Grafana Dashboard JSON 配置文件。

## 可用 Dashboard

### 1. 数据监控 (data-monitor.json)
监控数据采集状态和交易对价格。

### 2. 风险监控 (risk-monitor.json)
实时风险指标监控。

### 3. 回测结果 (backtest-results.json) 🆕
- **回测概览**: 总收益率、夏普比率、最大回撤、胜率、盈亏比、交易次数
- **权益曲线**: 策略权益随时间变化图
- **回撤水位**: 回撤深度可视化
- **策略对比**: 多策略回测结果表格对比
- **收益分布**: 每日收益率柱状图和直方图

## 使用方法

1. 启动基础设施:
   ```bash
   docker compose up -d influxdb grafana
   ```

2. 访问 Grafana: http://localhost:3000
   - 默认用户名: admin
   - 默认密码: admin

3. Dashboard 会通过 provisioning 自动加载
