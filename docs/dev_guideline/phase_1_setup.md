# Phase 1: 环境搭建与基础设施

**预计时间**: 1-2天  
**前置条件**: Docker 和 Docker Compose 已安装  
**目标**: 确保所有核心服务正常运行

## 步骤清单

### 1.1 环境变量配置

```bash
# 复制环境变量模板
cd /home/zihopc/vscode/AlgorithmTrader
cp .env.example .env

# 编辑 .env 文件，至少修改以下密码
# - INFLUXDB_ADMIN_PASSWORD
# - INFLUXDB_ADMIN_TOKEN (需要64位字符)
# - GF_SECURITY_ADMIN_PASSWORD  
# - POSTGRES_PASSWORD
# - MINIO_ROOT_PASSWORD
```

### 1.2 配置文件准备

#### 1.2.1 配置系统初始化
```bash
# 验证配置文件结构
ls -la config/
# 应该看到：
# data_collection.yml
# strategy.yml
# risk_management.yml
# monitoring.yml
# alerts.yml
```

#### 1.2.2 配置 Bark 推送通知
1. 在 iOS/Android 设备上安装 Bark 应用
2. 获取推送 URL（格式：https://api.day.app/your-key）
3. 更新 `config/alerts.yml` 中的 Bark 配置：

```yaml
bark:
  url: "https://api.day.app/your-key"  # 替换为你的 Bark URL
  title_prefix: "AlgoTrader"
  sound: "default"
  group: "trading"
```

#### 1.2.3 验证配置加载
```bash
cd /home/zihopc/vscode/AlgorithmTrader
python -c "
from apps.common.config_loader import load_data_collection_config
config = load_data_collection_config()
print('配置加载成功:', config.get('binance', {}).get('symbols', []))
"
```

### 1.3 启动核心服务

```bash
# 启动基础设施服务
docker-compose --profile core up -d

# 检查服务状态
docker-compose ps

# 预期输出：所有服务状态为 "running"
```

### 1.4 服务验证

#### InfluxDB 验证
```bash
# 访问 InfluxDB Web UI
# URL: http://localhost:8086
# 用户名: admin (或 .env 中的 INFLUXDB_ADMIN_USER)
# 密码: .env 中的 INFLUXDB_ADMIN_PASSWORD

# CLI 测试连接
docker exec -it algorithmtrader-influxdb influx auth list
```

#### Grafana 验证
```bash
# 访问 Grafana Web UI  
# URL: http://localhost:3000
# 用户名: admin (或 .env 中的 GF_SECURITY_ADMIN_USER)
# 密码: .env 中的 GF_SECURITY_ADMIN_PASSWORD

# 检查数据源配置
# Grafana UI -> Configuration -> Data Sources
# 应该看到预配置的 InfluxDB 数据源
```

#### PostgreSQL 验证
```bash
# 连接测试
docker exec -it algorithmtrader-postgres psql -U algouser -d algodb -c "\\dt"

# 预期：连接成功，显示空表列表
```

#### Redis 验证
```bash
# 连接测试  
docker exec -it algorithmtrader-redis redis-cli ping

# 预期输出: PONG
```

### 1.4 创建数据目录结构

```bash
# 创建数据湖目录
mkdir -p data/lake/crypto/spot/BTCUSDT
mkdir -p data/lake/crypto/spot/ETHUSDT  
mkdir -p data/lake/crypto/processed
mkdir -p data/cache/binance_downloads

# 设置权限
chmod -R 755 data/

# 验证目录结构
tree data/
```

### 1.5 网络连通性测试

```bash
# 测试容器间网络通信
docker exec algorithmtrader-grafana nslookup influxdb
docker exec algorithmtrader-grafana curl -f http://influxdb:8086/health

# 预期：DNS 解析成功，HTTP 200 响应
```

## 验收标准

### 服务状态检查
- [ ] InfluxDB 容器运行正常，Web UI 可访问
- [ ] Grafana 容器运行正常，Web UI 可访问  
- [ ] PostgreSQL 容器运行正常，可连接
- [ ] Redis 容器运行正常，响应 PING
- [ ] Loki 容器运行正常
- [ ] Promtail 容器运行正常

### 配置验证
- [ ] `.env` 文件配置正确，密码已修改
- [ ] 所有配置文件创建并验证可加载
- [ ] Bark 通知配置正确，能收到测试推送
- [ ] Docker 网络 quant-net 创建成功
- [ ] 持久化卷挂载正确
- [ ] 数据目录结构创建完整

### 功能测试
- [ ] Grafana 可以连接到 InfluxDB
- [ ] PostgreSQL 数据库可以创建表
- [ ] Redis 可以存储和读取数据
- [ ] 容器间网络通信正常

## 故障排除

### 常见问题

**端口冲突**:
```bash
# 检查端口占用
netstat -tulpn | grep :8086
netstat -tulpn | grep :3000

# 修改 .env 文件中的端口配置
```

**权限问题**:
```bash
# 检查 Docker 权限
sudo usermod -aG docker $USER
newgrp docker

# 检查数据目录权限
ls -la data/
```

**内存不足**:
```bash
# 检查系统资源
free -h
df -h

# 减少服务或增加虚拟内存
```

### 日志查看

```bash
# 查看所有服务日志
docker-compose logs

# 查看特定服务日志
docker-compose logs influxdb
docker-compose logs grafana

# 实时日志监控
docker-compose logs -f
```

## 下一步

完成 Phase 1 后，继续 Phase 2: 数据采集与存储

**检查点**:
- 所有核心服务运行正常
- Web UI 可以正常访问
- 数据库连接测试通过
- 目录结构创建完整

继续阅读: `phase_2_data_collection.md`
