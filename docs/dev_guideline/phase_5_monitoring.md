# Phase 5: 监控与告警

**预计时间**: 1天  
**前置条件**: Phase 4 完成，策略回测正常运行  
**目标**: 建立完整的系统监控、日志聚合和告警机制

## 步骤清单

### 5.1 创建监控模块

#### 目录结构
```bash
mkdir -p apps/monitoring
```

#### 健康检查组件

**apps/monitoring/health_check.py**
```python
"""
系统健康检查模块
监控各个组件的运行状态
"""
import os
import time
import json
import redis
import psycopg2
import requests
from datetime import datetime, timedelta
from influxdb_client import InfluxDBClient
from typing import Dict, List, Optional
import logging

class HealthChecker:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.redis_client = redis.Redis.from_url(os.getenv('REDIS_URL'))
        self.pg_conn_string = os.getenv('POSTGRES_URL')
        self.influx_client = InfluxDBClient(
            url=os.getenv('INFLUXDB_URL'),
            token=os.getenv('INFLUXDB_ADMIN_TOKEN'),
            org=os.getenv('INFLUXDB_ORG')
        )
        
    def check_redis(self) -> Dict:
        """检查Redis连接状态"""
        try:
            start_time = time.time()
            self.redis_client.ping()
            latency = (time.time() - start_time) * 1000
            
            info = self.redis_client.info()
            return {
                'status': 'healthy',
                'latency_ms': round(latency, 2),
                'memory_used': info.get('used_memory_human'),
                'connected_clients': info.get('connected_clients')
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e)
            }
    
    def check_postgres(self) -> Dict:
        """检查PostgreSQL连接状态"""
        try:
            start_time = time.time()
            conn = psycopg2.connect(self.pg_conn_string)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            latency = (time.time() - start_time) * 1000
            
            cursor.execute("SELECT count(*) FROM pg_stat_activity")
            active_connections = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            return {
                'status': 'healthy',
                'latency_ms': round(latency, 2),
                'active_connections': active_connections
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e)
            }
    
    def check_influxdb(self) -> Dict:
        """检查InfluxDB连接状态"""
        try:
            start_time = time.time()
            health = self.influx_client.health()
            latency = (time.time() - start_time) * 1000
            
            # 检查最近数据
            query = f'''
                from(bucket: "{os.getenv('INFLUXDB_BUCKET')}")
                |> range(start: -1h)
                |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
                |> count()
            '''
            tables = self.influx_client.query_api().query(query)
            
            recent_data_points = 0
            for table in tables:
                for record in table.records:
                    recent_data_points += record.get_value()
            
            return {
                'status': 'healthy' if health.status == 'pass' else 'unhealthy',
                'latency_ms': round(latency, 2),
                'recent_data_points': recent_data_points,
                'influx_status': health.status
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e)
            }
    
    def check_grafana(self) -> Dict:
        """检查Grafana连接状态"""
        try:
            start_time = time.time()
            response = requests.get(
                f"http://grafana:{os.getenv('GRAFANA_PORT', 3000)}/api/health",
                timeout=5
            )
            latency = (time.time() - start_time) * 1000
            
            return {
                'status': 'healthy' if response.status_code == 200 else 'unhealthy',
                'latency_ms': round(latency, 2),
                'response_code': response.status_code
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e)
            }
    
    def check_data_freshness(self) -> Dict:
        """检查数据新鲜度"""
        try:
            query = f'''
                from(bucket: "{os.getenv('INFLUXDB_BUCKET')}")
                |> range(start: -24h)
                |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
                |> last()
            '''
            tables = self.influx_client.query_api().query(query)
            
            latest_timestamp = None
            for table in tables:
                for record in table.records:
                    timestamp = record.get_time()
                    if not latest_timestamp or timestamp > latest_timestamp:
                        latest_timestamp = timestamp
            
            if latest_timestamp:
                age_minutes = (datetime.now(latest_timestamp.tzinfo) - latest_timestamp).total_seconds() / 60
                is_fresh = age_minutes < 60  # 数据不超过1小时算新鲜
                
                return {
                    'status': 'healthy' if is_fresh else 'stale',
                    'latest_timestamp': latest_timestamp.isoformat(),
                    'age_minutes': round(age_minutes, 2)
                }
            else:
                return {
                    'status': 'no_data',
                    'error': 'No recent data found'
                }
                
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def run_full_check(self) -> Dict:
        """运行完整的健康检查"""
        timestamp = datetime.utcnow().isoformat()
        
        checks = {
            'timestamp': timestamp,
            'redis': self.check_redis(),
            'postgres': self.check_postgres(),
            'influxdb': self.check_influxdb(),
            'grafana': self.check_grafana(),
            'data_freshness': self.check_data_freshness()
        }
        
        # 计算整体状态
        all_healthy = all(
            check.get('status') == 'healthy' 
            for check in checks.values() 
            if isinstance(check, dict) and 'status' in check
        )
        
        checks['overall_status'] = 'healthy' if all_healthy else 'unhealthy'
        
        return checks
```

#### 指标采集组件

**apps/monitoring/metrics.py**
```python
"""
业务指标采集模块
将指标写入InfluxDB的ops bucket
"""
import os
import psutil
import time
from datetime import datetime
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import logging

class MetricsCollector:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.influx_client = InfluxDBClient(
            url=os.getenv('INFLUXDB_URL'),
            token=os.getenv('INFLUXDB_ADMIN_TOKEN'),
            org=os.getenv('INFLUXDB_ORG')
        )
        self.write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)
        self.bucket = 'ops'  # 运营指标专用bucket
        
    def collect_system_metrics(self):
        """采集系统资源指标"""
        timestamp = datetime.utcnow()
        
        # CPU指标
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        
        # 内存指标
        memory = psutil.virtual_memory()
        
        # 磁盘指标
        disk = psutil.disk_usage('/')
        
        # 网络指标
        network = psutil.net_io_counters()
        
        points = [
            Point("ops_system")
            .tag("metric_type", "cpu")
            .field("cpu_percent", cpu_percent)
            .field("cpu_count", cpu_count)
            .time(timestamp),
            
            Point("ops_system")
            .tag("metric_type", "memory")
            .field("memory_total", memory.total)
            .field("memory_used", memory.used)
            .field("memory_percent", memory.percent)
            .time(timestamp),
            
            Point("ops_system")
            .tag("metric_type", "disk")
            .field("disk_total", disk.total)
            .field("disk_used", disk.used)
            .field("disk_percent", disk.used / disk.total * 100)
            .time(timestamp),
            
            Point("ops_system")
            .tag("metric_type", "network")
            .field("bytes_sent", network.bytes_sent)
            .field("bytes_recv", network.bytes_recv)
            .field("packets_sent", network.packets_sent)
            .field("packets_recv", network.packets_recv)
            .time(timestamp)
        ]
        
        try:
            self.write_api.write(bucket=self.bucket, org=os.getenv('INFLUXDB_ORG'), record=points)
            self.logger.debug("System metrics collected successfully")
        except Exception as e:
            self.logger.error(f"Failed to write system metrics: {e}")
    
    def collect_data_quality_metrics(self):
        """采集数据质量指标"""
        try:
            # 查询最近1小时的数据点数量
            query = f'''
                from(bucket: "{os.getenv('INFLUXDB_BUCKET')}")
                |> range(start: -1h)
                |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
                |> group(columns: ["symbol"])
                |> count()
            '''
            
            tables = self.influx_client.query_api().query(query)
            timestamp = datetime.utcnow()
            
            points = []
            for table in tables:
                for record in table.records:
                    symbol = record.values.get('symbol', 'unknown')
                    count = record.get_value()
                    
                    point = Point("ops_data_quality") \
                        .tag("symbol", symbol) \
                        .tag("metric_type", "data_points_1h") \
                        .field("count", count) \
                        .time(timestamp)
                    points.append(point)
            
            if points:
                self.write_api.write(bucket=self.bucket, org=os.getenv('INFLUXDB_ORG'), record=points)
                self.logger.debug(f"Data quality metrics collected for {len(points)} symbols")
                
        except Exception as e:
            self.logger.error(f"Failed to collect data quality metrics: {e}")
    
    def collect_application_metrics(self, app_name: str, custom_metrics: Dict):
        """采集应用自定义指标"""
        timestamp = datetime.utcnow()
        points = []
        
        for metric_name, value in custom_metrics.items():
            point = Point("ops_application") \
                .tag("app_name", app_name) \
                .tag("metric_name", metric_name) \
                .field("value", value) \
                .time(timestamp)
            points.append(point)
        
        try:
            self.write_api.write(bucket=self.bucket, org=os.getenv('INFLUXDB_ORG'), record=points)
            self.logger.debug(f"Application metrics collected for {app_name}")
        except Exception as e:
            self.logger.error(f"Failed to write application metrics: {e}")
```

#### 告警组件

**apps/monitoring/bark_notifier.py**
```python
"""
Bark 推送通知模块
"""
import os
import json
import yaml
import requests
from datetime import datetime
from typing import Dict, List
import logging

class BarkNotifier:
    def __init__(self, config_path="/config/alerts.yml"):
        self.logger = logging.getLogger(__name__)
        
        # 加载告警配置
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
            
        self.bark_config = self.config['bark']
        self.base_url = self.bark_config['server']['base_url']
        self.push_key = self.bark_config['push_key']
        
    def send_notification(self, alert: Dict):
        """发送 Bark 推送通知"""
        try:
            severity = alert.get('severity', 'medium')
            severity_config = self.bark_config['severity_config'].get(severity, {})
            
            # 构建推送消息
            title = f"🚨 {alert['title']}"
            body = self._format_message(alert)
            
            # 构建推送URL
            url = f"{self.base_url}/{self.push_key}/{title}/{body}"
            
            # 添加推送参数
            params = {
                'group': self.bark_config['default_config']['group'],
                'icon': self.bark_config['default_config']['icon'],
                'sound': severity_config.get('sound', 'default'),
                'level': severity_config.get('level', 'active')
            }
            
            # 严重告警特殊处理
            if severity == 'critical':
                if severity_config.get('call'):
                    params['call'] = '1'
                    
            # 发送推送
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 200:
                    self.logger.info(f"Bark notification sent successfully: {alert['title']}")
                    return True
                else:
                    self.logger.error(f"Bark API error: {result.get('message')}")
                    return False
            else:
                self.logger.error(f"Bark HTTP error: {response.status_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to send Bark notification: {e}")
            return False
    
    def _format_message(self, alert: Dict) -> str:
        """格式化告警消息"""
        severity_emojis = {
            'critical': '🔴',
            'high': '🟠',
            'medium': '🟡',
            'low': '🔵'
        }
        
        severity = alert.get('severity', 'medium')
        emoji = severity_emojis.get(severity, '⚪')
        
        message = f"{emoji} {alert.get('message', '')}\n"
        message += f"📊 组件: {alert.get('component', 'Unknown')}\n"
        message += f"⏰ 时间: {alert.get('timestamp', datetime.utcnow().isoformat())}\n"
        
        if alert.get('details'):
            message += f"📝 详情: {json.dumps(alert['details'], ensure_ascii=False, indent=2)}"
            
        return message
    
    def test_notification(self):
        """测试 Bark 连通性"""
        test_alert = {
            'title': 'AlgorithmTrader 测试通知',
            'message': '系统告警功能正常工作',
            'severity': 'low',
            'component': 'monitoring',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return self.send_notification(test_alert)
```

**apps/monitoring/alerts.py**
```python
"""
告警处理模块 - 使用 Bark 推送
"""
import os
import yaml
import json
from datetime import datetime, timedelta
from typing import Dict, List
import logging

from .bark_notifier import BarkNotifier

class AlertManager:
    def __init__(self, config_path="/config/alerts.yml"):
        self.logger = logging.getLogger(__name__)
        
        # 加载配置
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
            
        self.bark_notifier = BarkNotifier(config_path)
        self.alert_history = []
        self.suppression_cache = {}
        
    def check_alert_rules(self, metrics_data: Dict) -> List[Dict]:
        """检查告警规则"""
        alerts = []
        
        # 系统级告警检查
        alerts.extend(self._check_system_alerts(metrics_data))
        
        # 服务级告警检查
        alerts.extend(self._check_service_alerts(metrics_data))
        
        # 数据质量告警检查
        alerts.extend(self._check_data_quality_alerts(metrics_data))
        
        # 业务级告警检查
        alerts.extend(self._check_business_alerts(metrics_data))
        
        return alerts
    
    def _check_system_alerts(self, data: Dict) -> List[Dict]:
        """检查系统级告警"""
        alerts = []
        rules = self.config['alert_rules']['system_alerts']
        
        # CPU使用率检查
        cpu_usage = data.get('cpu_percent', 0)
        if cpu_usage > 90:
            alerts.append(self._create_alert(
                'cpu_usage_critical',
                f"CPU使用率严重: {cpu_usage}%",
                'critical',
                'system',
                {'cpu_usage': cpu_usage}
            ))
        elif cpu_usage > 80:
            alerts.append(self._create_alert(
                'cpu_usage_high',
                f"CPU使用率过高: {cpu_usage}%",
                'high',
                'system',
                {'cpu_usage': cpu_usage}
            ))
        
        # 内存使用率检查
        memory_usage = data.get('memory_percent', 0)
        if memory_usage > 95:
            alerts.append(self._create_alert(
                'memory_usage_critical',
                f"内存使用率严重: {memory_usage}%",
                'critical',
                'system',
                {'memory_usage': memory_usage}
            ))
        elif memory_usage > 85:
            alerts.append(self._create_alert(
                'memory_usage_high',
                f"内存使用率过高: {memory_usage}%",
                'high',
                'system',
                {'memory_usage': memory_usage}
            ))
        
        return alerts
    
    def _check_service_alerts(self, data: Dict) -> List[Dict]:
        """检查服务级告警"""
        alerts = []
        
        # 检查各服务健康状态
        services = ['influxdb', 'redis', 'postgres', 'grafana']
        for service in services:
            status = data.get(f'{service}_status')
            if status and status != 'healthy':
                severity = 'critical' if service == 'influxdb' else 'high'
                alerts.append(self._create_alert(
                    f'{service}_down',
                    f"{service.upper()}服务异常",
                    severity,
                    service,
                    {'status': status, 'error': data.get(f'{service}_error')}
                ))
        
        return alerts
    
    def _check_data_quality_alerts(self, data: Dict) -> List[Dict]:
        """检查数据质量告警"""
        alerts = []
        
        # 数据新鲜度检查
        data_age = data.get('data_age_minutes', 0)
        if data_age > 180:
            alerts.append(self._create_alert(
                'data_very_stale',
                f"市场数据严重延迟: {data_age}分钟未更新",
                'critical',
                'data_quality',
                {'age_minutes': data_age}
            ))
        elif data_age > 60:
            alerts.append(self._create_alert(
                'data_stale',
                f"市场数据延迟: {data_age}分钟未更新",
                'high',
                'data_quality',
                {'age_minutes': data_age}
            ))
        
        return alerts
    
    def _check_business_alerts(self, data: Dict) -> List[Dict]:
        """检查业务级告警"""
        alerts = []
        
        # 回撤检查
        drawdown = data.get('drawdown_percent', 0)
        if drawdown > 15:
            alerts.append(self._create_alert(
                'portfolio_drawdown_critical',
                f"组合回撤严重: {drawdown}%",
                'critical',
                'portfolio',
                {'drawdown': drawdown}
            ))
        elif drawdown > 10:
            alerts.append(self._create_alert(
                'portfolio_drawdown_high',
                f"组合回撤过高: {drawdown}%",
                'high',
                'portfolio',
                {'drawdown': drawdown}
            ))
        
        return alerts
    
    def _create_alert(self, name: str, message: str, severity: str, 
                     component: str, details: Dict) -> Dict:
        """创建告警对象"""
        return {
            'name': name,
            'title': name.replace('_', ' ').title(),
            'message': message,
            'severity': severity,
            'component': component,
            'timestamp': datetime.utcnow().isoformat(),
            'details': details
        }
    
    def process_alerts(self, alerts: List[Dict]):
        """处理告警列表"""
        for alert in alerts:
            # 检查告警抑制
            if self._should_suppress(alert):
                self.logger.debug(f"Alert suppressed: {alert['name']}")
                continue
                
            # 记录告警历史
            self.alert_history.append(alert)
            
            # 发送通知
            success = self.bark_notifier.send_notification(alert)
            
            if success:
                self.logger.info(f"Alert processed: {alert['name']}")
                # 更新抑制缓存
                self._update_suppression_cache(alert)
            else:
                self.logger.error(f"Failed to send alert: {alert['name']}")
    
    def _should_suppress(self, alert: Dict) -> bool:
        """检查是否应该抑制告警"""
        alert_key = f"{alert['component']}_{alert['name']}"
        suppression_time = self.config['global']['suppression_time']
        
        if alert_key in self.suppression_cache:
            last_sent = self.suppression_cache[alert_key]
            if (datetime.utcnow() - last_sent).total_seconds() < suppression_time:
                return True
                
        return False
    
    def _update_suppression_cache(self, alert: Dict):
        """更新告警抑制缓存"""
        alert_key = f"{alert['component']}_{alert['name']}"
        self.suppression_cache[alert_key] = datetime.utcnow()
```

### 5.2 创建监控主程序

**apps/monitoring/main.py**
```python
"""
监控主程序
定期运行健康检查和指标采集，使用YAML配置文件
"""
import os
import time
import json
import yaml
import logging
from datetime import datetime

from health_check import HealthChecker
from metrics import MetricsCollector
from alerts import AlertManager

def load_config(config_path="/config/monitoring.yml"):
    """加载监控配置"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def setup_logging(config):
    """配置日志"""
    log_level = config['logging']['level']
    log_format = config['logging']['format']
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format=log_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('/var/log/monitoring.log')
        ]
    )

def main():
    # 加载配置
    config = load_config()
    setup_logging(config)
    
    logger = logging.getLogger(__name__)
    
    # 初始化组件
    health_checker = HealthChecker()
    metrics_collector = MetricsCollector()
    alert_manager = AlertManager()
    
    # 监控间隔(秒)
    interval = config['global']['check_interval']
    
    logger.info("Monitoring system started with config-driven approach")
    
    while True:
        try:
            start_time = time.time()
            
            # 运行健康检查
            health_data = health_checker.run_full_check()
            logger.info(f"Health check completed: {health_data['overall_status']}")
            
            # 采集系统指标
            metrics_collector.collect_system_metrics()
            
            # 采集数据质量指标
            metrics_collector.collect_data_quality_metrics()
            
            # 检查告警规则
            alerts = alert_manager.check_alert_rules(health_data)
            if alerts:
                alert_manager.process_alerts(alerts)
            
            # 记录监控系统自身的指标
            execution_time = time.time() - start_time
            metrics_collector.collect_application_metrics('monitoring', {
                'execution_time_seconds': execution_time,
                'alerts_generated': len(alerts),
                'health_check_duration': execution_time
            })
            
            # 保存健康检查结果到文件
            with open('/tmp/health_status.json', 'w') as f:
                json.dump(health_data, f, indent=2, default=str)
            
            # 等待下次检查
            time.sleep(max(0, interval - execution_time))
            
        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user")
            break
        except Exception as e:
            logger.error(f"Monitoring error: {e}", exc_info=True)
            time.sleep(interval)

if __name__ == "__main__":
    main()
```

### 5.3 Docker化监控服务

**apps/monitoring/Dockerfile**
```dockerfile
FROM python:3.11-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 创建日志目录
RUN mkdir -p /var/log

ENV PYTHONPATH=/app
ENV TZ=UTC

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import json; print(json.load(open('/tmp/health_status.json'))['overall_status'])" || exit 1

CMD ["python", "main.py"]
```

**apps/monitoring/requirements.txt**
```
psutil>=5.9.0
redis>=4.5.0
psycopg2-binary>=2.9.0
influxdb-client>=1.36.0
requests>=2.31.0
PyYAML>=6.0
```

### 5.4 更新Docker Compose配置

在 `docker-compose.yml` 中添加监控服务：

```yaml
  monitoring:
    build: ./apps/monitoring
    container_name: ${COMPOSE_PROJECT_NAME:-algorithmtrader}-monitoring
    profiles: ["apps"]
    restart: unless-stopped
    environment:
      - TZ=${TZ:-UTC}
      - INFLUXDB_URL=${INFLUXDB_URL}
      - INFLUXDB_ADMIN_TOKEN=${INFLUXDB_ADMIN_TOKEN}
      - INFLUXDB_ORG=${INFLUXDB_ORG}
      - REDIS_URL=${REDIS_URL}
      - POSTGRES_URL=${POSTGRES_URL}
      - GRAFANA_PORT=${GRAFANA_PORT}
    volumes:
      - /var/log/algorithmtrader:/var/log
      - ./config:/config:ro    # 挂载配置文件目录(只读)
    depends_on:
      - influxdb
      - redis
      - postgres
      - grafana
    networks:
      - quant-net
```

### 5.5 创建系统健康面板

在Grafana中创建系统监控面板：

#### 面板1: 服务状态概览
```flux
from(bucket: "ops")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "ops_system")
  |> filter(fn: (r) => r._field == "cpu_percent" or r._field == "memory_percent")
  |> aggregateWindow(every: v.windowPeriod, fn: mean)
```

#### 面板2: 数据质量监控
```flux
from(bucket: "ops")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "ops_data_quality")
  |> filter(fn: (r) => r._field == "count")
  |> group(columns: ["symbol"])
```

#### 面板3: 告警历史
显示最近的告警事件和系统状态变化

### 5.6 设置Grafana告警规则

1. 在Grafana中创建告警规则：
   - CPU使用率 > 80%
   - 内存使用率 > 90%
   - 磁盘使用率 > 85%
   - 数据超过1小时未更新

2. 配置通知渠道：
   - 邮件通知
   - Webhook通知（可选）

### 5.7 启动监控服务

```bash
# 启动监控服务
docker-compose --profile apps up -d monitoring

# 检查服务状态
docker-compose ps monitoring

# 查看日志
docker-compose logs -f monitoring
```

## 验收标准

### 健康检查
- [ ] 所有组件健康状态检查正常
- [ ] 连接延迟测试通过
- [ ] 数据新鲜度检查准确
- [ ] 健康状态文件正确输出

### 指标采集
- [ ] 系统资源指标正确采集
- [ ] 数据质量指标准确
- [ ] 应用自定义指标正常
- [ ] InfluxDB写入成功

### 告警功能
- [ ] 告警规则触发正确
- [ ] 邮件通知发送成功
- [ ] 告警日志记录完整
- [ ] 告警抑制机制工作

### 可视化
- [ ] Grafana监控面板显示正确
- [ ] 告警规则配置生效
- [ ] 通知渠道测试通过
- [ ] 历史数据查询正常

## 故障排除

### 健康检查问题
```bash
# 检查网络连通性
docker exec algorithmtrader-monitoring ping influxdb
docker exec algorithmtrader-monitoring ping redis
docker exec algorithmtrader-monitoring ping postgres

# 检查服务端口
docker exec algorithmtrader-monitoring netstat -tulpn
```

### 指标采集问题
```bash
# 检查InfluxDB ops bucket
docker exec algorithmtrader-influxdb influx bucket list

# 创建ops bucket(如果不存在)
docker exec algorithmtrader-influxdb influx bucket create --name ops --org quant --retention 8760h

# 验证指标写入
docker exec algorithmtrader-influxdb influx query 'from(bucket: "ops") |> range(start: -1h) |> count()'
```

### 告警问题
```bash
# 测试 Bark 推送
python -c "
from apps.monitoring.bark_notifier import BarkNotifier

notifier = BarkNotifier()
test_result = notifier.test_notification()
print(f'Bark test result: {test_result}')
"

# 检查配置文件
cat config/alerts.yml | grep -A 10 bark

# 测试告警规则
python -c "
from apps.monitoring.alerts import AlertManager

alert_manager = AlertManager()
test_data = {'cpu_percent': 95, 'memory_percent': 88}
alerts = alert_manager.check_alert_rules(test_data)
print(f'Generated {len(alerts)} alerts')
for alert in alerts:
    print(f'- {alert[\"name\"]}: {alert[\"message\"]}')
"
```

### Grafana问题
```bash
# 检查数据源配置
curl -u admin:password http://localhost:3000/api/datasources

# 测试Flux查询
curl -u admin:password \
  -XPOST http://localhost:3000/api/ds/query \
  -H "Content-Type: application/json" \
  -d '{"queries":[{"datasource":{"uid":"influxdb"},"refId":"A","query":"from(bucket: \"ops\") |> range(start: -1h) |> limit(n: 10)"}]}'
```

## 完成MVP

恭喜！完成Phase 5后，您的加密货币量化交易系统MVP已经搭建完成。

**系统功能概览**:
✅ **数据采集**: BTC/ETH历史数据下载和存储  
✅ **数据存储**: InfluxDB时序数据库 + Parquet数据湖  
✅ **数据可视化**: Grafana仪表盘展示市场数据  
✅ **策略引擎**: 双均线策略实现和回测  
✅ **监控告警**: 完整的系统监控和告警机制  

**下一步扩展建议**:
1. 添加更多技术指标和策略
2. 接入实时数据流
3. 扩展到更多交易对
4. 实现风险管理模块
5. 准备实盘交易接口

系统现在可以作为学习和实验平台，为后续的功能扩展打下坚实基础。
