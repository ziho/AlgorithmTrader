# Data Guide

The data import module of this project is designed to fetch spot 1-second data from Binance and allows users to add their preferred trading pairs as needed. The downloaded data will be stored within the `download` folder.

## Data Source

- **Source**: [Binance Public Data](https://github.com/binance/binance-public-data)
- **Data Type**: Spot 1s Data

## Download script

```bash
python3 download-kline.py -t spot -s BTCUSDT -skip-monthly 1
```

## Supported Trading Pairs

Initially, the following trading pairs are supported:

```python
symbols = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT',
    'DOGEUSDT', 'SOLUSDT', 'LTCUSDT', 'AVAXUSDT', 'LINKUSDT'
]