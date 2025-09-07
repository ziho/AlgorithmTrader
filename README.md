AlgorithmTrader (scaffold)
==========================

Docker-only, research-to-live scaffold for a personal mid/low-frequency trading system. Code runs in containers only (see docs/vibe_rule.md).

Quick start
-----------
1) Copy env template and review ports/users (no real secrets):
	cp .env.example .env

2) Start core infra (InfluxDB, Grafana, Postgres, Redis, Loki, Promtail):
	docker compose --profile core up -d

3) Optional: start MinIO object store:
	docker compose --profile optional up -d minio

4) Open Grafana: http://<SERVER_IP>:3000 (use credentials from .env).

Project layout (dirs only)
-------------------------
- infra/: compose, secrets placeholders, dashboards
- apps/: services skeleton (collectors, features, strategy, risk, execution, adapters, monitoring, common)
- data/: lake/ and cache/ (UTC-only data)
- models/: trained artifacts registry (future)
- research/: notebooks and playbooks
- docs/: architecture and guidelines (no secrets)
- tests/: unit and integration

Notes
-----
- No local execution. Use Docker.
- New features default off; enable via profiles/config.
- Data must be in UTC and time-safe (no look-ahead).

Recover after reboot (core stack)
---------------------------------
1) Ensure env exists (placeholders OK):
	cp -n .env.example .env

2) Start core services:
	sudo docker compose --profile core up -d

3) Check statuses:
	sudo docker compose ps

4) Health checks (replace <SERVER_IP> if not localhost):
	curl -sSf http://<SERVER_IP>:3000/api/health   # Grafana
	curl -sSf http://<SERVER_IP>:8086/health       # InfluxDB
	curl -sSf http://<SERVER_IP>:3100/ready        # Loki

5) Useful ops:
	sudo docker compose logs -f loki               # tail logs
	sudo docker compose restart loki               # restart one
	sudo docker compose --profile core down        # stop core
