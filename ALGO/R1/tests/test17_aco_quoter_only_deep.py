"""
test17: Pure deep-tier passive — quote ONLY at fair±3 (offset 3).
Expected: fills at better prices (±3 edge) when market trades at deep prices;
misses fills at shallower prices.
"""
import json
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self): self.logs = ""; self.max_log_length = 3750
    def print(self, *o, sep=" ", end="\n"): self.logs += sep.join(map(str, o)) + end
    def flush(self, state, orders, conversions, trader_data):
        base = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", ""]))
        mil = (self.max_log_length - base) // 3
        print(self.to_json([self.compress_state(state, self.truncate(state.traderData, mil)),
                            self.compress_orders(orders), conversions,
                            self.truncate(trader_data, mil), self.truncate(self.logs, mil)]))
        self.logs = ""
    def compress_state(self, s, td):
        return [s.timestamp, td, [[l.symbol, l.product, l.denomination] for l in s.listings.values()],
                {k: [v.buy_orders, v.sell_orders] for k, v in s.order_depths.items()},
                [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp] for a in s.own_trades.values() for t in a],
                [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp] for a in s.market_trades.values() for t in a],
                s.position,
                [s.observations.plainValueObservations,
                 {p: [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff, o.importTariff, o.sugarPrice, o.sunlightIndex]
                  for p, o in s.observations.conversionObservations.items()}]]
    def compress_orders(self, orders):
        return [[o.symbol, o.price, o.quantity] for a in orders.values() for o in a]
    def to_json(self, v): return json.dumps(v, cls=ProsperityEncoder, separators=(",", ":"))
    def truncate(self, v, m):
        lo, hi = 0, min(len(v), m); out = ""
        while lo <= hi:
            mid = (lo + hi) // 2; c = v[:mid]
            if len(c) < len(v): c += "..."
            if len(json.dumps(c)) <= m: out = c; lo = mid + 1
            else: hi = mid - 1
        return out


logger = Logger()


class Trader:
    POSITION_LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
    FAIR = 10000
    OFFSET = 3
    SIZE = 30

    def run(self, state: TradingState):
        result = {}
        for product, od in state.order_depths.items():
            orders = []
            pos = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 80)
            if not od.buy_orders or not od.sell_orders:
                result[product] = orders
                continue
            bb, ba = max(od.buy_orders), min(od.sell_orders)
            if product == "INTARIAN_PEPPER_ROOT":
                q = limit - pos
                if q > 0: orders.append(Order(product, ba, q))
            elif product == "ASH_COATED_OSMIUM":
                rb = max(0, limit - pos); rs = max(0, limit + pos)
                # Aggressive take at ≤ 9999
                for p in sorted(od.sell_orders):
                    if p <= self.FAIR - 1 and rb > 0:
                        q = min(rb, -od.sell_orders[p])
                        if q > 0: orders.append(Order(product, p, q)); rb -= q
                    else: break
                for p in sorted(od.buy_orders, reverse=True):
                    if p >= self.FAIR + 1 and rs > 0:
                        q = min(rs, od.buy_orders[p])
                        if q > 0: orders.append(Order(product, p, -q)); rs -= q
                    else: break
                # Only deep passive
                bp = self.FAIR - self.OFFSET
                ap = self.FAIR + self.OFFSET
                pbq = min(self.SIZE, rb); psq = min(self.SIZE, rs)
                if pbq > 0: orders.append(Order(product, bp, pbq))
                if psq > 0: orders.append(Order(product, ap, -psq))
            result[product] = orders
        logger.flush(state, result, 0, "")
        return result, 0, ""
