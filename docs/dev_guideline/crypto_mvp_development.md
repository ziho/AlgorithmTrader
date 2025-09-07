# 加密货币量化交易系统 MVP 开发指南

**版本**: v1.0  
**创建日期**: 2025-09-07  
**遵循**: vibe_rule.md 规范  

## 变更摘要

本次开发将实现一个最小可行的加密货币量化交易系统，包含：
- BTC/ETH 历史数据采集与存储（过去3年，1分钟级别）
- InfluxDB 时序数据存储 + Grafana 可视化
- 简单双均线策略（MA5 vs MA20）
- 基础回测框架
- 监控告警系统（使用 Bark 推送通知）
- 基于 YAML 的配置管理系统

**核心特性**:
- ✅ 数据驱动：基于币安公开数据源
- ✅ 容器化部署：Docker Compose 编排
- ✅ 时序存储：InfluxDB + Parquet 数据湖
- ✅ 可视化：Grafana 仪表盘
- ✅ 策略引擎：可扩展框架
- ✅ 监控告警：Bark 移动推送 + 完整观测性
- ✅ 配置管理：YAML 配置文件，业务配置与基础设施分离

## 文件改动清单

### 新增文件
```
apps/
├── collectors/
│   ├── crypto/
│   │   ├── __init__.py
│   │   ├── downloader.py          # Binance 数据下载器
│   │   ├── validator.py           # 数据验证清洗
│   │   ├── influx_writer.py       # InfluxDB 写入器
│   │   └── config_loader.py       # 配置加载器
│   ├── Dockerfile
│   └── requirements.txt
├── common/
│   ├── __init__.py
│   ├── events.py                  # 事件模型定义
│   ├── database.py                # 数据库连接管理
│   ├── logger.py                  # 统一日志配置
│   ├── config_loader.py           # YAML配置加载器
│   └── utils.py                   # 工具函数
├── strategy_engine/
│   ├── __init__.py
│   ├── base_strategy.py           # 策略基类
│   ├── ma_strategy.py             # 双均线策略
│   ├── backtest.py                # 回测引擎
│   ├── config_loader.py           # 策略配置加载
│   ├── Dockerfile
│   └── requirements.txt
└── monitoring/
    ├── __init__.py
    ├── metrics.py                 # 指标采集
    ├── health_check.py            # 健康检查
    ├── bark_notifier.py           # Bark推送通知
    └── alerts.py                  # 告警逻辑

config/
├── data_collection.yml           # 数据采集配置
├── strategy.yml                  # 策略引擎配置
├── risk_management.yml           # 风险管理配置
├── monitoring.yml                # 监控配置
├── alerts.yml                    # 告警配置(使用Bark)
├── grafana/
│   └── dashboards/
│       ├── crypto_overview.json   # 加密货币概览面板
│       ├── strategy_performance.json # 策略表现面板
│       └── system_health.json     # 系统健康面板
└── influxdb/
    └── retention_policies.flux     # 数据保留策略

docs/dev_guideline/
├── crypto_mvp_development.md      # 本文档
├── config_management.md           # 配置管理说明
├── phase_1_setup.md               # 第一阶段：环境搭建
├── phase_2_data_collection.md     # 第二阶段：数据采集
├── phase_3_visualization.md       # 第三阶段：可视化
├── phase_4_strategy.md            # 第四阶段：策略开发
└── phase_5_monitoring.md          # 第五阶段：监控告警

data/
├── lake/
│   └── crypto/
│       ├── spot/
│       │   ├── BTCUSDT/
│       │   └── ETHUSDT/
│       └── processed/
└── cache/
    └── binance_downloads/
```

### 修改文件
```
.env.example                       # 移除业务配置，保留基础设施配置
docker-compose.yml                 # 新增应用服务定义（注释状态）
```

## Patch Plan (分阶段实施方案)

### Phase 1: 环境搭建与基础设施 (1-2天)

**目标**: 确保 Docker 环境正常运行，数据库连通性

**步骤**:
1. 复制 `.env.example` 为 `.env`，修改必要密码
2. 启动核心服务：`docker-compose --profile core up -d`
3. 验证服务状态：InfluxDB、Grafana、Postgres、Redis
4. 创建数据目录结构

**验收标准**:
- [ ] 所有核心服务运行正常（绿色状态）
- [ ] Grafana 可访问（http://localhost:3000）
- [ ] InfluxDB 可访问（http://localhost:8086）
- [ ] 数据目录创建成功

**详细步骤**: 见 `docs/dev_guideline/phase_1_setup.md`

### Phase 2: 数据采集与存储 (2-3天)

**目标**: 下载并处理 BTC/ETH 历史数据，存储到 InfluxDB

**步骤**:
1. 开发 Binance 数据下载器
2. 实现数据验证与清洗逻辑
3. 批量导入 InfluxDB
4. 建立 Parquet 数据湖

**验收标准**:
- [ ] 成功下载 BTC/ETH 过去3年1分钟数据
- [ ] 数据质量检查通过（无重复、无缺失）
- [ ] InfluxDB 包含完整时序数据
- [ ] Parquet 文件正确分区存储

**详细步骤**: 见 `docs/dev_guideline/phase_2_data_collection.md`

### Phase 3: 数据可视化 (1-2天)

**目标**: 创建 Grafana 仪表盘展示市场数据

**步骤**:
1. 配置 InfluxDB 数据源
2. 创建加密货币概览面板
3. 添加价格图表、成交量、技术指标
4. 设置数据刷新频率

**验收标准**:
- [ ] 价格K线图正确显示
- [ ] 成交量图表准确
- [ ] 时间范围选择器工作正常
- [ ] 数据自动刷新

**详细步骤**: 见 `docs/dev_guideline/phase_3_visualization.md`

### Phase 4: 策略开发与回测 (2-3天)

**目标**: 实现双均线策略，完成历史回测

**步骤**:
1. 开发策略框架基类
2. 实现双均线策略（MA5 vs MA20）
3. 建立回测引擎
4. 计算策略表现指标

**验收标准**:
- [ ] 策略信号生成正确
- [ ] 回测结果合理（包含交易费用）
- [ ] 生成策略表现报告
- [ ] Grafana 策略面板展示

**详细步骤**: 见 `docs/dev_guideline/phase_4_strategy.md`

### Phase 5: 监控与告警 (1天)

**目标**: 建立系统监控和告警机制

**步骤**:
1. 实现健康检查探针
2. 配置关键指标监控
3. 设置告警规则
4. 测试告警通知

**验收标准**:
- [ ] 系统健康状态可见
- [ ] 数据采集监控正常
- [ ] 告警规则触发测试通过
- [ ] 日志聚合功能正常

**详细步骤**: 见 `docs/dev_guideline/phase_5_monitoring.md`

## 验收与监控

### 系统验收检查单

**基础设施**:
- [ ] Docker 容器全部运行正常
- [ ] 数据库连接测试通过
- [ ] 网络通信正常
- [ ] 数据持久化配置正确

**数据层**:
- [ ] 历史数据完整性检查通过
- [ ] InfluxDB 查询性能符合预期
- [ ] Parquet 文件读取正常
- [ ] 数据更新机制工作正常

**策略层**:
- [ ] 策略信号生成逻辑正确
- [ ] 回测结果符合预期
- [ ] 风险控制参数有效
- [ ] 性能指标计算准确

**监控层**:
- [ ] Grafana 面板数据正确
- [ ] 告警规则配置有效
- [ ] 日志收集正常
- [ ] 健康检查响应及时

### 关键监控指标

**系统指标**:
- 容器运行状态与资源使用
- 数据库连接数与响应时间
- 磁盘使用量与网络流量

**业务指标**:
- 数据采集延迟与成功率
- 策略信号生成频率
- 回测计算耗时
- 数据质量得分

**告警阈值**:
- 数据中断超过5分钟
- 系统CPU使用率超过80%
- 内存使用率超过90%
- 磁盘使用率超过85%

## 回滚方案

### 数据回滚
- 保留原始下载数据备份
- InfluxDB 数据导出脚本
- Parquet 文件版本管理

### 配置回滚
- Docker Compose 配置版本控制
- 环境变量备份文件
- Grafana 面板导出

### 应用回滚
- 容器镜像标签管理
- 数据库 schema 迁移脚本
- 服务降级预案

### 紧急停机
```bash
# 停止所有服务
docker-compose down

# 仅停止应用服务，保留基础设施
docker-compose stop collector-crypto strategy-engine

# 数据备份
docker exec algorithmtrader-influxdb influx backup /backup
```

## 风险分析

### 技术风险

**数据风险**:
- **风险**: Binance API 限制或数据源变更
- **缓解**: 本地数据缓存，多数据源备份计划
- **监控**: API 调用成功率，数据完整性检查

**性能风险**:
- **风险**: 大量历史数据导致查询缓慢
- **缓解**: 合理的数据分区和索引策略
- **监控**: 查询响应时间，资源使用率

**存储风险**:
- **风险**: 磁盘空间不足
- **缓解**: 数据保留策略，定期清理
- **监控**: 磁盘使用率告警

### 业务风险

**策略风险**:
- **风险**: 简单策略可能不具备实际盈利能力
- **缓解**: 明确本项目为技术验证，非投资建议
- **监控**: 策略表现跟踪，风险指标监控

**运维风险**:
- **风险**: 系统故障影响数据采集
- **缓解**: 容器自动重启，数据补采机制
- **监控**: 服务可用性，故障恢复时间

### 合规风险

**数据使用**:
- **风险**: 数据使用超出许可范围
- **缓解**: 严格遵循 Binance 公开数据使用条款
- **监控**: 数据来源合规性审查

**安全风险**:
- **风险**: 敏感信息泄露
- **缓解**: 遵循 vibe_rule.md，禁止真实凭据
- **监控**: 代码审查，环境变量检查

## 后续扩展计划

### 短期目标 (1-2个月)
- 新增更多技术指标（RSI、MACD、布林带）
- 实现实时数据采集（WebSocket）
- 添加更多交易对（ADA、SOL、MATIC）
- 策略参数优化功能

### 中期目标 (3-6个月)
- 接入美股数据源
- 机器学习策略框架
- 期货合约支持
- 风险管理模块

### 长期目标 (6-12个月)
- 多市场套利策略
- C++ 性能优化
- 实盘交易接口
- 完整的产品化

## 开发规范提醒

### 遵循 vibe_rule.md
1. ✅ 仅通过 Docker 运行，禁止本地调试
2. ✅ 文档放在 docs/dev_guideline/
3. ✅ 修改前进行必要性分析
4. ✅ 新功能默认关闭，配置启用
5. ✅ 禁止输出真实凭据
6. ✅ 数据写入 UTC 时区
7. ✅ 声明日志字段和指标
8. ✅ 提供回滚方案和风险分析

### 代码质量
- 使用类型提示 (Type Hints)
- 编写单元测试
- 遵循 PEP 8 规范
- 添加必要的文档字符串

### Git 工作流
- 功能分支开发
- 提交信息规范
- 代码审查流程
- 版本标签管理

---

**注意**: 本系统仅用于技术学习和验证，不构成任何投资建议。请遵循相关法律法规，谨慎进行实盘交易。
