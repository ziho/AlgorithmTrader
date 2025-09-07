AlgorithmTrader
===============

Docker-only, research-to-live scaffold for a personal mid/low-frequency trading system.

Status
------
- Core infra up via Docker Compose (Grafana, InfluxDB, Postgres, Redis, Loki, Promtail)
- Provisioned Grafana data sources for Loki/InfluxDB

Prerequisites
-------------
- Linux server (root Docker only per vibe_rule)
- Docker Engine + Compose plugin

Quick start
-----------
1) Copy env template (placeholders only):
    ```
	cp .env.example .env
    ```

2) Start core infra (InfluxDB, Grafana, Postgres, Redis, Loki, Promtail):
	```
    sudo docker compose --profile core up -d
    ```

3) Optional: MinIO:
    ```
	sudo docker compose --profile optional up -d minio
    ```

4) Open Grafana: `http://<SERVER_IP>:3000` (use credentials from .env)

Recovery (after reboot)
-----------------------
1) Ensure env exists:
	`cp -n .env.example .env`

2) Start core:
	`sudo docker compose --profile core up -d`

3) Check:
	`sudo docker compose ps`

4) Health:
	```
    curl -sSf http://<SERVER_IP>:3000/api/health   # Grafana
	curl -sSf http://<SERVER_IP>:8086/health       # InfluxDB
	curl -sSf http://<SERVER_IP>:3100/ready        # Loki
    ```

Operations
----------
- Tail logs: `sudo docker compose logs -f loki`
- Restart one: `sudo docker compose restart grafana`
- Stop core: `sudo docker compose --profile core down`

Configuration
-------------
- Edit `.env` (copied from `.env.example`). No real secrets in repo.
- Grafana datasources provisioned from `config/grafana/provisioning`.
- `Loki/Promtail` configs in `config/` (UTC expected).

Project structure
-----------------
- See `documents/dev_guideline/folders_overview.md` for folder purposes.
- `apps/`, `infra/`, `data/`, `models/`, `research/`, `docs/`, `tests/` scaffolded per `docs/Overall.md`.

Profiles
--------
- core: Grafana, InfluxDB, Postgres, Redis, Loki, Promtail
- optional: MinIO
- apps: application services (placeholders, disabled by default)

Policy
------
- No local runs. Docker only. Data is UTC; no look-ahead.
- New features off by default; enable via config/profiles.

License
-------
See LICENSE.
