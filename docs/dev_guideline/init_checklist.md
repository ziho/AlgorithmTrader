# Init Checklist

Minimal steps to bring up core and get ready for app development.

1) Env files
- Copy template: cp -n .env.example .env
- Adjust ports/users if needed. Do not commit secrets.

2) Start core stack (root-only)
- sudo docker compose --profile core up -d
- Verify: sudo docker compose ps
- Health: Grafana /api/health, InfluxDB /health, Loki /ready

3) Grafana
- Login with credentials from .env
- Datasources pre-provisioned (Loki, InfluxDB)

4) Logs & metrics
- Promtail ships host & Docker logs to Loki
- Use Grafana Explore > Loki for log search

5) Data lake
- Timestamps in UTC only; avoid look-ahead in features/labels

6) Next steps
- Define event/data contracts in apps/common
- Implement collectors → feature_engine → backtests → strategy → risk → execution
