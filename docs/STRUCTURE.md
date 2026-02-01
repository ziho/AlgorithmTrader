# 📚 文档组织总结

## 文件夹结构

```
docs/
├── README.md                           # 文档中心主页（导航枢纽）
│
├── guides/                             # 用户指南与操作手册
│   ├── user_guide.md                   # 系统完整使用手册
│   ├── strategy_development.md         # 策略开发完整指南
│   ├── deployment.md                   # 生产环境部署指南
│   ├── faq.md                          # 常见问题解答
│   └── [其他指南]
│
├── tutorials/                          # 学习教程
│   ├── quickstart.md                   # 10分钟快速开始
│   ├── first_strategy.md               # 编写第一个策略（手把手）
│   ├── parameter_optimization.md       # 策略参数优化
│   └── [其他教程]
│
├── templates/                          # 模板文件
│   ├── strategy_template.md            # 策略需求文档模板
│   ├── strategy_design_template.md     # 策略设计模板（详细版）
│   ├── strategy_config_template.json   # 策略配置模板
│   └── backtest_config_template.json   # 回测配置模板
│
├── development/                        # 开发文档（架构与规划）
│   ├── architecture.md                 # 系统架构详解
│   ├── init_requirement.md             # 初始需求分析
│   ├── init_GPT5.2Thinking.md          # 架构设计思路
│   └── phase1&2_web_optimization.md    # Web界面开发规划
│
└── api/                                # API 参考文档
    ├── strategy_api.md                 # 策略接口文档
    ├── data_api.md                     # 数据接口文档
    ├── backtest_api.md                 # 回测接口文档
    └── execution_api.md                # 执行接口文档
```

## 文档分类

### 📖 用户指南 (guides/)

用户在实际使用系统时查阅的文档。

| 文件 | 用途 | 何时阅读 |
|------|------|---------|
| `user_guide.md` | 系统全面介绍 | 第一次使用 |
| `strategy_development.md` | 如何编写策略 | 开发策略时 |
| `deployment.md` | 部署到服务器 | 上生产前 |
| `faq.md` | 常见问题 | 遇到问题时 |

### 🎓 学习教程 (tutorials/)

逐步引导用户学习的教程。

| 文件 | 内容 | 难度 |
|------|------|------|
| `quickstart.md` | 10分钟快速体验 | ⭐ 入门 |
| `first_strategy.md` | 手把手写策略 | ⭐⭐ 初级 |
| `parameter_optimization.md` | 优化策略参数 | ⭐⭐⭐ 中级 |

### 📋 模板文件 (templates/)

帮助用户快速开始的模板。

- `strategy_template.md` - 记录策略思路
- `strategy_design_template.md` - 详细的策略设计文档
- `strategy_config_template.json` - 策略配置示例
- `backtest_config_template.json` - 回测配置示例

### 🏗️ 开发文档 (development/)

系统设计、规划、Prompt 等技术文档。

- `architecture.md` - 系统架构详解
- `init_requirement.md` - 项目初始需求
- `init_GPT5.2Thinking.md` - 架构设计思路
- `phase1&2_web_optimization.md` - Web 界面规划

### 🔌 API 参考 (api/)

各模块的 API 接口文档。

- `strategy_api.md` - StrategyBase 接口
- `data_api.md` - 数据接口
- `backtest_api.md` - 回测接口
- `execution_api.md` - 订单执行接口

## 使用流程

### 新用户流程

```
README.md (导航)
    ↓
quickstart.md (快速上手)
    ↓
first_strategy.md (写第一个策略)
    ↓
strategy_development.md (深入学习)
    ↓
deployment.md (上生产)
```

### 遇到问题

```
specific question
    ↓
faq.md (查找常见问题)
    ↓
对应的 guide
    ↓
GitHub Issues
```

### 开发者参考

```
architecture.md (理解设计)
    ↓
相应模块的 API 文档
    ↓
源代码注释
```

## 最佳实践

### 📝 查阅文档

1. 从 `README.md` 开始理解整体结构
2. 根据具体需求选择相应的 guide 或 tutorial
3. 使用 templates 快速开始
4. 遇到问题先查 FAQ

### 📚 维护文档

1. **及时更新**: 代码改变时更新文档
2. **清晰示例**: 提供可运行的代码示例
3. **实际检验**: 文档中的命令必须能实际运行
4. **表达自然**: 用清晰的语言，避免过度技术化

### 🎯 文档写作

- **层次清晰**: 使用标题分层，便于扫读
- **示例充分**: 每个概念配对应示例
- **链接相关**: 相关内容互相链接
- **定期更新**: 保持文档与代码同步

## 新增文档

如果需要新增文档，请遵循以下原则：

### 何时新增

- 功能逻辑复杂需要详细说明
- 常见问题频繁被问到
- 新的模块或功能上线
- 特殊的部署或配置场景

### 放在哪里

- **如何使用**: `guides/`
- **学习教程**: `tutorials/`
- **架构/规划**: `development/`
- **模板示例**: `templates/`
- **API 参考**: `api/`

### 文档模板

```markdown
# [文档标题]

> [简短描述]

## 目录

- [section1](#section1)
- [section2](#section2)

## 前置条件

[安装/配置/先决知识]

## 主要内容

### Section 1
[详细说明]

### Section 2
[详细说明]

## 常见问题

### Q: ...
**A**: ...

## 下一步

- [相关文档]
- [相关教程]

---

**版本**: v1.0
**最后更新**: YYYY-MM-DD
```

## 文档维护计划

### Q1 优先级

- [ ] 完成所有 guides 文档
- [ ] 完成所有 tutorials
- [ ] 完成 API 参考

### Q2 优先级

- [ ] 添加视频教程链接
- [ ] 创建快速参考卡片
- [ ] 建立 Wiki 系统

### Q3 及以后

- [ ] 国际化（英文版本）
- [ ] 深入的架构设计文档
- [ ] 性能优化指南
- [ ] 安全最佳实践

## 相关资源

### 系统中的其他文档

- `README.md` - 项目主页
- `pyproject.toml` - 项目配置
- `.github/` - GitHub Actions 配置
- `infra/*/README.md` - 各基础设施组件

### 外部资源

- [Python 官方文档](https://docs.python.org/3/)
- [Docker 文档](https://docs.docker.com/)
- [InfluxDB 文档](https://docs.influxdata.com/)
- [Grafana 文档](https://grafana.com/docs/)

---

**最后更新**: 2026-02-01

**反馈**: 如果文档不清楚或有错误，欢迎提交 Issue 或 PR！
