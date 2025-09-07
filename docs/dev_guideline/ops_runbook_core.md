# Ops Runbook (Core Stack)

Start/Stop
- Start: sudo docker compose --profile core up -d
- Stop: sudo docker compose --profile core down
- Restart one: sudo docker compose restart <service>
- Status: sudo docker compose ps

Health checks
- Grafana: curl -sSf http://<SERVER_IP>:3000/api/health
- InfluxDB: curl -sSf http://<SERVER_IP>:8086/health
- Loki: curl -sSf http://<SERVER_IP>:3100/ready

Logs
- Tail service: sudo docker compose logs -f <service>

Notes
- Root Docker only per vibe_rule.
- Avoid storing any credentials in repo; use .env locally.
