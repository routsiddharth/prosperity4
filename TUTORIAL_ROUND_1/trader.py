import json
import math
from typing import Any, Dict, List

from datamodel import OrderDepth, TradingState, Order, Symbol, Trade


class Trader:
    POSITION_LIMITS: Dict[str, int] = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    # EMERALDS
    EMERALDS_FAIR = 10000
    EMERALDS_SKEW = 0.10
    EMERALDS_BASE_SIZE = 15

    # TOMATOES
    TOMATO_FAST_ALPHA = 0.4
    TOMATO_SLOW_ALPHA = 0.05
    TOMATO_SKEW = 0.18
    TOMATO_BASE_SIZE = 12
    TOMATO_WINDOW = 15

    # Trade flow
    FLOW_IMPACT = 0.3
    FLOW_DECAY = 0.7

    def run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        result: Dict[Symbol, List[Order]] = {}
        data = self.load_data(state.traderData)

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            position = state.position.get(product, 0)

            if order_depth.buy_orders and order_depth.sell_orders:
                wmid = self.weighted_mid(order_depth)
                pd = data.setdefault(
                    product, {"fast_ema": None, "slow_ema": None, "prices": [], "flow": 0.0}
                )

                # Update EMAs
                if pd["fast_ema"] is None:
                    pd["fast_ema"] = wmid
                    pd["slow_ema"] = wmid
                else:
                    pd["fast_ema"] = self.TOMATO_FAST_ALPHA * wmid + (1 - self.TOMATO_FAST_ALPHA) * pd["fast_ema"]
                    pd["slow_ema"] = self.TOMATO_SLOW_ALPHA * wmid + (1 - self.TOMATO_SLOW_ALPHA) * pd["slow_ema"]

                pd["prices"].append(wmid)
                pd["prices"] = pd["prices"][-self.TOMATO_WINDOW:]

                # Trade flow: smoothed net buy pressure
                flow = self.compute_trade_flow(
                    state.market_trades.get(product, []), order_depth
                )
                pd["flow"] = self.FLOW_DECAY * pd["flow"] + (1 - self.FLOW_DECAY) * flow

                if product == "EMERALDS":
                    orders = self.emeralds_orders(order_depth, position, pd)
                elif product == "TOMATOES":
                    orders = self.tomatoes_orders(order_depth, position, pd)

            result[product] = orders

        return result, 0, json.dumps(data)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def weighted_mid(od: OrderDepth) -> float:
        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)
        bid_vol = od.buy_orders[best_bid]
        ask_vol = -od.sell_orders[best_ask]
        total = bid_vol + ask_vol
        if total == 0:
            return (best_bid + best_ask) / 2
        # High bid volume -> price more likely to rise -> wmid shifts toward ask
        return (best_bid * ask_vol + best_ask * bid_vol) / total

    @staticmethod
    def compute_trade_flow(trades: List[Trade], od: OrderDepth) -> float:
        if not trades:
            return 0.0
        mid = (max(od.buy_orders) + min(od.sell_orders)) / 2
        flow = 0.0
        for trade in trades:
            if trade.price >= mid:
                flow += trade.quantity  # buyer-initiated
            else:
                flow -= trade.quantity  # seller-initiated
        return flow

    @staticmethod
    def rolling_vol(prices: List[float]) -> float:
        if len(prices) < 2:
            return 0.0
        diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        mean = sum(diffs) / len(diffs)
        var = sum((d - mean) ** 2 for d in diffs) / len(diffs)
        return math.sqrt(var)

    def load_data(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {}
        try:
            loaded = json.loads(trader_data)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    # -------------------------------------------------------------- EMERALDS

    def emeralds_orders(
        self, od: OrderDepth, position: int, pd: Dict
    ) -> List[Order]:
        product = "EMERALDS"
        limit = self.POSITION_LIMITS[product]
        orders: List[Order] = []

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)

        # Fair value: stable anchor + micro flow adjustment
        fair = self.EMERALDS_FAIR + self.FLOW_IMPACT * pd["flow"]

        current_pos = position

        # --- Aggressive taking: take_width = 0 (tighter than 80861's 0.5) ---
        buy_cap = limit - current_pos
        for ask_price in sorted(od.sell_orders):
            if ask_price > fair:
                break
            qty = min(-od.sell_orders[ask_price], buy_cap)
            if qty > 0:
                orders.append(Order(product, ask_price, qty))
                current_pos += qty
                buy_cap -= qty

        sell_cap = limit + current_pos
        for bid_price in sorted(od.buy_orders, reverse=True):
            if bid_price < fair:
                break
            qty = min(od.buy_orders[bid_price], sell_cap)
            if qty > 0:
                orders.append(Order(product, bid_price, -qty))
                current_pos -= qty
                sell_cap -= qty

        # --- Passive: penny pricing + asymmetric sizing ---
        buy_cap = limit - current_pos
        sell_cap = limit + current_pos

        skew = self.EMERALDS_SKEW * current_pos
        reservation = fair - skew

        bid_quote = min(best_bid + 1, math.floor(reservation))
        ask_quote = max(best_ask - 1, math.ceil(reservation))

        if bid_quote >= ask_quote:
            bid_quote = min(best_bid, math.floor(fair))
            ask_quote = max(best_ask, math.ceil(fair))

        # Asymmetric sizing: bigger on the inventory-reducing side
        buy_size = self.EMERALDS_BASE_SIZE + max(0, -current_pos) // 4
        sell_size = self.EMERALDS_BASE_SIZE + max(0, current_pos) // 4

        # Level 1: penny the best price
        if buy_cap > 0 and bid_quote < best_ask:
            qty = min(buy_size, buy_cap)
            orders.append(Order(product, bid_quote, qty))
            buy_cap -= qty

        if sell_cap > 0 and ask_quote > best_bid:
            qty = min(sell_size, sell_cap)
            orders.append(Order(product, ask_quote, -qty))
            sell_cap -= qty

        # Level 2: wider quote to catch larger moves
        bid2 = bid_quote - 2
        ask2 = ask_quote + 2
        if buy_cap > 0 and bid2 > 0:
            orders.append(Order(product, bid2, min(8, buy_cap)))
        if sell_cap > 0:
            orders.append(Order(product, ask2, -min(8, sell_cap)))

        return orders

    # -------------------------------------------------------------- TOMATOES

    def tomatoes_orders(
        self, od: OrderDepth, position: int, pd: Dict
    ) -> List[Order]:
        product = "TOMATOES"
        limit = self.POSITION_LIMITS[product]
        orders: List[Order] = []

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)

        fast_ema = pd["fast_ema"]
        slow_ema = pd["slow_ema"]
        flow = pd["flow"]
        vol = self.rolling_vol(pd["prices"])

        # Dual-EMA fair value: fast center + trend bias + flow
        trend_bias = (fast_ema - slow_ema) * 0.3
        fair = fast_ema + self.FLOW_IMPACT * flow + trend_bias

        current_pos = position

        # --- Aggressive taking: vol-adjusted, trend-biased ---
        base_take = max(0.5, min(2.0, 0.5 + 0.35 * vol))

        # Easier to take in the trend direction
        if trend_bias > 0.5:
            buy_take = base_take * 0.7
            sell_take = base_take * 1.3
        elif trend_bias < -0.5:
            buy_take = base_take * 1.3
            sell_take = base_take * 0.7
        else:
            buy_take = base_take
            sell_take = base_take

        buy_cap = limit - current_pos
        for ask_price in sorted(od.sell_orders):
            if ask_price > fair - buy_take:
                break
            qty = min(-od.sell_orders[ask_price], buy_cap)
            if qty > 0:
                orders.append(Order(product, ask_price, qty))
                current_pos += qty
                buy_cap -= qty

        sell_cap = limit + current_pos
        for bid_price in sorted(od.buy_orders, reverse=True):
            if bid_price < fair + sell_take:
                break
            qty = min(od.buy_orders[bid_price], sell_cap)
            if qty > 0:
                orders.append(Order(product, bid_price, -qty))
                current_pos -= qty
                sell_cap -= qty

        # --- Passive: regime-adaptive + penny pricing + asymmetric ---
        buy_cap = limit - current_pos
        sell_cap = limit + current_pos

        skew = self.TOMATO_SKEW * current_pos
        reservation = fair - skew

        # Volatility regime: adjust spread width and size
        if vol < 1.5:
            spread_add = 0
            base_size = self.TOMATO_BASE_SIZE + 2
        elif vol < 3.0:
            spread_add = 1
            base_size = self.TOMATO_BASE_SIZE
        else:
            spread_add = 2
            base_size = self.TOMATO_BASE_SIZE - 4

        bid_quote = min(best_bid + 1, math.floor(reservation) - spread_add)
        ask_quote = max(best_ask - 1, math.ceil(reservation) + spread_add)

        if bid_quote >= ask_quote:
            bid_quote = min(best_bid, math.floor(fair))
            ask_quote = max(best_ask, math.ceil(fair))

        # Asymmetric sizing
        buy_size = base_size + max(0, -current_pos) // 4
        sell_size = base_size + max(0, current_pos) // 4

        # Level 1: penny
        if buy_cap > 0 and bid_quote < best_ask:
            qty = min(buy_size, buy_cap)
            orders.append(Order(product, bid_quote, qty))
            buy_cap -= qty

        if sell_cap > 0 and ask_quote > best_bid:
            qty = min(sell_size, sell_cap)
            orders.append(Order(product, ask_quote, -qty))
            sell_cap -= qty

        # Level 2: wider for depth
        bid2 = bid_quote - 3
        ask2 = ask_quote + 3
        if buy_cap > 0 and bid2 > 0:
            orders.append(Order(product, bid2, min(5, buy_cap)))
        if sell_cap > 0:
            orders.append(Order(product, ask2, -min(5, sell_cap)))

        return orders
