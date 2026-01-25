"""
Trader 服务 - 实盘交易

职责:
- 等待 bar close 触发
- 运行策略生成信号
- 风控检查
- 调用 Broker 下单
"""
