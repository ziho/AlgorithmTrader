# Phase 2: 数据采集与存储

**预计时间**: 2-3天  
**前置条件**: Phase 1 完成，所有核心服务正常运行  
**目标**: 建立完整的数据采集、验证、存储管道

## 步骤清单

### 2.1 创建数据采集器模块

#### 创建目录结构
```bash
mkdir -p apps/collectors/crypto
mkdir -p apps/common
```

#### 数据采集器实现

**apps/collectors/crypto/downloader.py**
```python
"""
Binance 历史数据下载器
基于 research/referrepos/binance-public-data 工具
"""
import os
import requests
import zipfile
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import logging

class BinanceDataDownloader:
    def __init__(self, base_url="https://data.binance.vision/"):
        self.base_url = base_url
        self.logger = logging.getLogger(__name__)
        
    def download_klines(self, symbol, interval, start_date, end_date, data_type="spot"):
        """下载指定时间范围的K线数据"""
        # 实现月度数据下载逻辑
        pass
        
    def validate_and_extract(self, zip_path, output_dir):
        """验证并解压数据文件"""
        # CHECKSUM 验证逻辑
        pass
```

**apps/collectors/crypto/validator.py**
```python
"""
数据验证与清洗模块
"""
import pandas as pd
import numpy as np
from typing import Tuple, List

class DataValidator:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    def validate_ohlcv(self, df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """验证OHLCV数据完整性"""
        errors = []
        
        # 检查必要列
        required_cols = ['open_time', 'open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            errors.append(f"Missing columns: {missing_cols}")
            
        # 检查数据类型
        # 检查时间连续性  
        # 检查价格合理性 (high >= low, etc.)
        # 检查重复数据
        
        return len(errors) == 0, errors
        
    def clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗数据"""
        # 去重、填充缺失值、时区转换等
        pass
```

**apps/collectors/crypto/influx_writer.py**
```python
"""
InfluxDB 数据写入器
"""
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import pandas as pd

class InfluxWriter:
    def __init__(self, url, token, org, bucket):
        self.client = InfluxDBClient(url=url, token=token, org=org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.bucket = bucket
        self.org = org
        
    def write_ohlcv(self, df: pd.DataFrame, symbol: str):
        """写入OHLCV数据到InfluxDB"""
        points = []
        for index, row in df.iterrows():
            point = Point("crypto_ohlcv_1m") \
                .tag("symbol", symbol) \
                .tag("exchange", "binance") \
                .field("open", float(row['open'])) \
                .field("high", float(row['high'])) \
                .field("low", float(row['low'])) \
                .field("close", float(row['close'])) \
                .field("volume", float(row['volume'])) \
                .time(row['open_time'])
            points.append(point)
            
        self.write_api.write(bucket=self.bucket, org=self.org, record=points)
```

### 2.2 实现数据下载脚本

**apps/collectors/crypto/main.py**
```python
"""
主数据采集脚本
"""
import os
import sys
from datetime import datetime, timedelta
import pandas as pd

from downloader import BinanceDataDownloader  
from validator import DataValidator
from influx_writer import InfluxWriter

def main():
    # 从环境变量读取配置
    symbols = os.getenv('BINANCE_DATA_SYMBOLS', 'BTCUSDT,ETHUSDT').split(',')
    interval = os.getenv('BINANCE_DATA_INTERVAL', '1m')
    start_date = os.getenv('BINANCE_DATA_START_DATE', '2022-01-01')
    end_date = os.getenv('BINANCE_DATA_END_DATE', '2025-01-01')
    
    # 初始化组件
    downloader = BinanceDataDownloader()
    validator = DataValidator()
    influx_writer = InfluxWriter(
        url=os.getenv('INFLUXDB_URL'),
        token=os.getenv('INFLUXDB_ADMIN_TOKEN'),
        org=os.getenv('INFLUXDB_ORG'),
        bucket=os.getenv('INFLUXDB_BUCKET')
    )
    
    # 处理每个交易对
    for symbol in symbols:
        print(f"Processing {symbol}...")
        
        # 下载数据
        raw_data = downloader.download_klines(symbol, interval, start_date, end_date)
        
        # 验证数据
        is_valid, errors = validator.validate_ohlcv(raw_data)
        if not is_valid:
            print(f"Data validation failed for {symbol}: {errors}")
            continue
            
        # 清洗数据
        clean_data = validator.clean_data(raw_data)
        
        # 写入InfluxDB
        influx_writer.write_ohlcv(clean_data, symbol)
        
        # 保存到Parquet
        output_path = f"/data/lake/crypto/spot/{symbol}/{symbol}_1m_historical.parquet"
        clean_data.to_parquet(output_path, index=False)
        
        print(f"Completed {symbol}: {len(clean_data)} records")

if __name__ == "__main__":
    main()
```

### 2.3 Docker 化采集器

**apps/collectors/Dockerfile**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# 设置环境变量
ENV PYTHONPATH=/app
ENV TZ=UTC

# 运行采集器
CMD ["python", "crypto/main.py"]
```

**apps/collectors/requirements.txt**
```
pandas>=2.0.0
requests>=2.31.0
influxdb-client>=1.36.0
pyarrow>=12.0.0
numpy>=1.24.0
python-dateutil>=2.8.2
```

### 2.4 数据库schema初始化

**初始化InfluxDB**
```bash
# 进入InfluxDB容器
docker exec -it algorithmtrader-influxdb influx

# 创建bucket (如果不存在)
influx bucket create --name marketdata --org quant --retention 4320h

# 创建数据保留策略
influx task create --file /config/retention_policies.flux
```

**config/influxdb/retention_policies.flux**
```flux
option task = {name: "data_retention", every: 24h}

// 删除超过180天的原始数据
from(bucket: "marketdata")
  |> range(start: -180d, stop: now())
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> aggregateWindow(every: 1d, fn: mean)
  |> to(bucket: "marketdata_daily")
```

### 2.5 运行数据采集

```bash
# 构建采集器镜像
cd apps/collectors
docker build -t crypto-collector .

# 运行数据采集（一次性任务）
docker run --rm \
  --network algorithmtrader_quant-net \
  --env-file ../../.env \
  -v $(pwd)/../../data:/data \
  crypto-collector
```

### 2.6 验证数据采集结果

#### 检查InfluxDB数据
```bash
# 进入InfluxDB容器查询
docker exec -it algorithmtrader-influxdb influx query '
from(bucket: "marketdata")
  |> range(start: -1y)
  |> filter(fn: (r) => r._measurement == "crypto_ohlcv_1m")
  |> filter(fn: (r) => r.symbol == "BTCUSDT")
  |> count()
'
```

#### 检查Parquet文件
```bash
# 验证Parquet文件
ls -la data/lake/crypto/spot/BTCUSDT/
python -c "
import pandas as pd
df = pd.read_parquet('data/lake/crypto/spot/BTCUSDT/BTCUSDT_1m_historical.parquet')
print(f'Records: {len(df)}')
print(f'Date range: {df.open_time.min()} to {df.open_time.max()}')
print(df.head())
"
```

## 验收标准

### 数据完整性
- [ ] BTC/ETH 过去3年数据下载完成
- [ ] 数据时间连续性检查通过
- [ ] 无重复记录
- [ ] 价格数据合理性验证通过

### 存储验证  
- [ ] InfluxDB 包含完整的时序数据
- [ ] Parquet 文件格式正确
- [ ] 数据目录结构符合规范
- [ ] 文件权限设置正确

### 性能指标
- [ ] 数据下载速度: >1000 records/sec
- [ ] InfluxDB写入性能: >500 points/sec  
- [ ] Parquet文件大小合理 (<100MB per symbol per year)
- [ ] 内存使用稳定 (<2GB peak)

## 故障排除

### 网络问题
```bash
# 测试Binance API连通性
curl -I https://data.binance.vision/

# 检查DNS解析
nslookup data.binance.vision
```

### 存储问题  
```bash
# 检查磁盘空间
df -h

# 检查目录权限
ls -la data/lake/crypto/

# 清理临时文件
rm -rf data/cache/binance_downloads/*.zip
```

### InfluxDB问题
```bash
# 检查InfluxDB状态
docker exec algorithmtrader-influxdb influx ping

# 查看错误日志  
docker logs algorithmtrader-influxdb

# 重启InfluxDB
docker-compose restart influxdb
```

## 下一步

完成Phase 2后，继续Phase 3: 数据可视化

**检查点**:
- 历史数据采集完成
- InfluxDB查询正常
- Parquet文件可读取
- 数据质量验证通过

继续阅读: `phase_3_visualization.md`
