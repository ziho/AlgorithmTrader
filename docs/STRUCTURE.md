# 文档结构与关系

本文档描述 `docs/` 的真实结构与推荐阅读路径，方便维护时快速定位。

## 目录结构

```
docs/
├── README.md
├── STRUCTURE.md
├── KNOWN_LIMITATIONS.md
├── guides/
│   ├── user_guide.md
│   ├── strategy_development.md
│   ├── data_collection.md
│   ├── deployment.md
│   ├── web_ui.md
│   └── faq.md
├── tutorials/
│   ├── quickstart.md
│   └── first_strategy.md
├── templates/
│   ├── strategy_design_template.md
│   ├── strategy_template.md
│   ├── strategy_config_template.json
│   └── backtest_config_template.json
└── development/
    ├── architecture.md
    ├── phase1&2_web_optimization.md
    └── tushare_a_share_integration.md
```

## 文档定位

- `README.md`：文档入口与导航
- `KNOWN_LIMITATIONS.md`：功能状态与已知限制
- `guides/`：面向使用者的操作与流程说明
- `tutorials/`：循序渐进的上手教程
- `templates/`：策略与配置模板
- `development/`：架构与技术方案

## 推荐阅读路径

### 新用户

1. `README.md`
2. `tutorials/quickstart.md`
3. `tutorials/first_strategy.md`
4. `guides/strategy_development.md`

### 运维/部署

1. `guides/deployment.md`
2. `guides/web_ui.md`
3. `guides/faq.md`

### 研发/规划

1. `development/architecture.md`
2. `development/phase1&2_web_optimization.md`
3. `development/tushare_a_share_integration.md`

## 维护原则

1. 代码有变更时同步更新文档。
2. 文档链接只指向实际存在的文件。
3. 示例命令以可执行为准。
4. 内容保持简洁、直接、可复用。
