"""
策略基类

接口设计:
- on_bar(bar_frame) -> target_position | order_intent
- on_fill(fill_event) -> None

研究/回测/实盘共用同一接口
"""
