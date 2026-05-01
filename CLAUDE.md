# Prosperity 4 — Project Instructions

## Algo Trading Reference Docs

Before working on ANY algorithmic trading round task, ALWAYS read these reference docs first:

- `ALGO/algo_trading_reference.md` — Full algorithm writing guide: Trader class structure, TradingState API, OrderDepth, Order, Trade, position limits, order execution mechanics, conversions, supported libraries, datamodel.py, and common patterns
- `backtester_reference.md` — Local backtester CLI usage, flags, data format, order matching logic, position limits, output log format, and visualizer

These docs define the exchange rules, data model, and testing tools. Refer to them to ensure algorithms are correct w.r.t. position limit enforcement, order signing conventions (positive=buy, negative=sell), sell_orders having negative quantities, and the 3-tuple return signature `(result, conversions, traderData)`.
