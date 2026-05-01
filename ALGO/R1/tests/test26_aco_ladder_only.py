"""
test26: Pure ladder, no aggressive take. See if aggressive take was redundant.
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
    BID_LADDER = [(14, 3), (13, 3), (12, 3), (11, 3), (10, 3), (9, 3), (8, 3),
                  (7, 3), (6, 3), (5, 3), (4, 3), (3, 3), (2, 5), (1, 20)]
    ASK_LADDER = [(14, 3), (13, 3), (12, 3), (11, 3), (10, 3), (9, 3), (8, 3),
                  (7, 3), (6, 3), (5, 3), (4, 3), (3, 3), (2, 5), (1, 20)]

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
                fair = self.FAIR
                rb = max(0, limit - pos); rs = max(0, limit + pos)
                for offset, sz in self.BID_LADDER:
                    if rb <= 0: break
                    q = min(sz, rb)
                    if q > 0: orders.append(Order(product, fair - offset, q)); rb -= q
                for offset, sz in self.ASK_LADDER:
                    if rs <= 0: break
                    q = min(sz, rs)
                    if q > 0: orders.append(Order(product, fair + offset, -q)); rs -= q
            result[product] = orders
        logger.flush(state, result, 0, "")
        return result, 0, ""
