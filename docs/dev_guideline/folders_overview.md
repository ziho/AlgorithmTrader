# Folders Overview

Short purposes for each dir (≤100 words). Place process docs here per vibe_rule.

- infra/: Infra and orchestration. Compose files, secrets placeholders, dashboards.
  - infra/compose/: Compose manifests for profiles (core/optional/apps).
  - infra/secrets/: Secret placeholders (use Docker secrets/Vault in prod).
  - infra/dashboards/: Grafana dashboards JSON and notes.
- apps/: Services monorepo: collectors, feature engine, qlib bridge, backtests, strategy, risk, execution, adapters, monitoring, common libs.
  - apps/collectors/: Market data ingest, validator, resampler.
  - apps/feature_engine/: Feature/factor pipelines.
  - apps/qlib_service/: Qlib integration and data bridge.
  - apps/backtest_runner/: Batch backtests, WF, sweeps.
  - apps/strategy_engine/: Output target weights/signals.
  - apps/risk_engine/: Pre/in/post-trade risk checks.
  - apps/execution_router/: Routing/slicing (TWAP/VWAP/POV).
  - apps/adapters/: Broker/exchange adapters (binance/ib/xtp/paper).
  - apps/monitoring/: Metrics, logs, health probes.
  - apps/common/: Event models, calendar, config, contracts.
- data/: Data lake and caches. UTC only; no look-ahead.
  - data/lake/: Parquet/Arrow by market/date/symbol.
  - data/cache/: Intermediates and QC.
- models/: Trained models and versions.
- research/: Notebooks and playbooks.
- docs/: Existing docs; add new dev docs in docs/dev_guideline.
- tests/: Unit and integration (paper broker playback).