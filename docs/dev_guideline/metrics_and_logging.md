# Metrics and Logging

Loki/Promtail
- Promtail scrapes /var/log/*.log and Docker containers; pushes to Loki.
- Explore logs in Grafana > Explore > Loki.

InfluxDB
- Use for ops.* metrics and marketdata buckets.
- Configure dashboards under infra/dashboards (JSON not included yet).

Conventions
- Timestamps in UTC.
- Structured log fields: service, market, symbol, order_id, latency_ms, risk_code.
- Metrics: ops.* for latency, queue, error rate, fill ratio, pnl, drawdown.
