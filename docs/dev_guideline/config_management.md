# 配置管理说明

## 概述

AlgorithmTrader 使用基于 YAML 的配置管理系统，将业务配置从环境变量中分离，提供更好的可维护性和可读性。

## 配置文件结构

```
config/
├── data_collection.yml    # 数据采集配置
├── strategy.yml          # 策略引擎配置  
├── risk_management.yml   # 风险管理配置
├── monitoring.yml        # 监控配置
└── alerts.yml           # 告警配置(使用Bark)
```

## 配置使用方式

### 1. 使用配置加载器

```python
from apps.common.config_loader import (
    load_data_collection_config,
    get_binance_symbols,
    get_bark_config
)

# 加载完整配置
config = load_data_collection_config()

# 获取特定值
symbols = get_binance_symbols()
bark_config = get_bark_config()
```

### 2. 在应用中集成

```python
# 数据采集器示例
from apps.common.config_loader import config_loader

class DataCollector:
    def __init__(self):
        self.config = config_loader.load_config('data_collection')
        self.symbols = self.config['binance']['symbols']
        self.interval = self.config['binance']['interval']
```

### 3. 配置热重载

```python
# 重新加载单个配置
config_loader.reload_config('strategy')

# 重新加载所有配置
config_loader.reload_all_configs()
```

## Bark 配置说明

### 1. 获取 Bark 推送密钥

1. 在 App Store 下载 Bark 应用
2. 打开应用，复制推送密钥
3. 修改 `config/alerts.yml` 中的 `push_key`

### 2. 配置示例

```yaml
bark:
  server:
    base_url: "https://api.day.app"
  push_key: "YOUR_ACTUAL_BARK_KEY_HERE"
  default_config:
    group: "AlgorithmTrader"
    sound: "default"
```

### 3. 自建 Bark 服务器

如需使用自建服务器，修改 `base_url`:
```yaml
bark:
  server:
    base_url: "http://your-bark-server.com"
```

## 配置验证

### 1. 检查配置文件语法

```bash
# 验证 YAML 语法
python -c "
import yaml
with open('config/alerts.yml') as f:
    config = yaml.safe_load(f)
    print('Config is valid')
"
```

### 2. 测试 Bark 连通性

```bash
# 测试 Bark 推送
python -c "
from apps.common.config_loader import get_bark_config
from apps.monitoring.bark_notifier import BarkNotifier

bark_config = get_bark_config()
print(f'Bark server: {bark_config[\"server\"][\"base_url\"]}')

notifier = BarkNotifier()
result = notifier.test_notification()
print(f'Test result: {result}')
"
```

## 配置更新最佳实践

### 1. 配置变更流程

1. 修改配置文件
2. 验证语法正确性
3. 测试配置功能
4. 重启相关服务或热重载

### 2. 环境隔离

```yaml
# 开发环境
monitoring:
  global:
    check_interval: 30  # 更频繁的检查

# 生产环境  
monitoring:
  global:
    check_interval: 60  # 标准检查间隔
```

### 3. 敏感信息处理

敏感信息如 Bark 密钥应该通过环境变量或密钥管理系统注入：

```yaml
bark:
  push_key: "${BARK_PUSH_KEY}"  # 从环境变量读取
```

## 故障排除

### 常见问题

1. **配置文件找不到**
   - 检查文件路径和权限
   - 确认 Docker 容器挂载正确

2. **YAML 语法错误**
   - 使用在线 YAML 验证器检查
   - 注意缩进和特殊字符

3. **Bark 推送失败**
   - 检查网络连通性
   - 验证推送密钥正确性
   - 查看 Bark 服务状态
