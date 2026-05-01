from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Any
import json


class Trader:
    PRODUCT = "ROBOT_DISHES"
    LIMIT = 10

    # =====================================================
    # HISTORY / REGIME
    # =====================================================
    HISTORY_LIMIT = 1500

    REGIME_WINDOW = 600
    MIN_HISTORY = 600

    ACF1_THRESHOLD = -0.08
    ZERO_RATE_THRESHOLD = 0.30
    NET_MOVE_THRESHOLD = 150

    # =====================================================
    # DISHES TAKER ALPHA
    # =====================================================
    FAIR_WINDOW = 10
    TAKER_THRESHOLD = 3.0
    TAKER_SIZE = 4

    # =====================================================
    # MAX LOSS / KILL SWITCH
    # =====================================================
    MAX_LOSS = -1000
    KILL_SWITCH_KEY = "killed"

    # =====================================================
    # MAIN
    # =====================================================

    def run(self, state: TradingState):
        data = self.load_data(state.traderData)
        orders_by_product: Dict[str, List[Order]] = {}

        if self.PRODUCT not in state.order_depths:
            return {}, 0, json.dumps(data)

        od = state.order_depths[self.PRODUCT]
        position = int(state.position.get(self.PRODUCT, 0))

        if not od.buy_orders or not od.sell_orders:
            return {}, 0, json.dumps(data)

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)
        mid = (best_bid + best_ask) / 2

        # =====================================================
        # PNL TRACKING / MAX LOSS
        # =====================================================

        if "cash" not in data:
            data["cash"] = 0.0

        if "last_position" not in data:
            data["last_position"] = position

        if self.KILL_SWITCH_KEY not in data:
            data[self.KILL_SWITCH_KEY] = False

        prev_pos = int(data.get("last_position", 0))
        delta_pos = position - prev_pos

        # Approximate fill price using current mid
        data["cash"] -= delta_pos * mid
        data["last_position"] = position

        mtm_pnl = data["cash"] + position * mid
        data["mtm_pnl"] = mtm_pnl

        if mtm_pnl <= self.MAX_LOSS:
            data[self.KILL_SWITCH_KEY] = True

        if data.get(self.KILL_SWITCH_KEY, False):
            orders_by_product[self.PRODUCT] = self.flatten_position(od, position)
            return orders_by_product, 0, json.dumps(data)

        # =====================================================
        # NORMAL TRADING
        # =====================================================

        orders = self.trade_dishes(od, position, data)
        orders_by_product[self.PRODUCT] = orders

        return orders_by_product, 0, json.dumps(data)

    # =====================================================
    # CORE LOGIC
    # =====================================================

    def trade_dishes(
        self,
        od: OrderDepth,
        position: int,
        data: Dict[str, Any],
    ) -> List[Order]:

        orders: List[Order] = []

        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)

        bid_vol = int(od.buy_orders[best_bid])
        ask_vol = -int(od.sell_orders[best_ask])

        mid = (best_bid + best_ask) / 2
        spread = best_ask - best_bid

        self.update_history(mid, data)

        taker_enabled = self.regime_ok(data)

        # =====================================================
        # TAKER ALPHA
        # =====================================================

        if taker_enabled:
            orders += self.taker_alpha(
                best_bid,
                best_ask,
                bid_vol,
                ask_vol,
                position,
                data,
            )

        used_buy = sum(o.quantity for o in orders if o.quantity > 0)
        used_sell = -sum(o.quantity for o in orders if o.quantity < 0)
        effective_position = position + used_buy - used_sell

        # =====================================================
        # DEFENSIVE MM
        # =====================================================

        if taker_enabled:
            base_size = 1
            max_size = 2
            min_spread = 7
        else:
            base_size = 1
            max_size = 1
            min_spread = 8

        orders += self.defensive_mm(
            best_bid,
            best_ask,
            bid_vol,
            ask_vol,
            effective_position,
            spread,
            base_size,
            max_size,
            min_spread,
        )

        return orders

    # =====================================================
    # REGIME FILTER
    # =====================================================

    def regime_ok(self, data: Dict[str, Any]) -> bool:
        mids = data.get("mid", [])

        if len(mids) < self.MIN_HISTORY:
            return False

        window = mids[-self.REGIME_WINDOW:]

        diffs = []
        zero_count = 0

        for i in range(1, len(window)):
            d = window[i] - window[i - 1]
            diffs.append(d)
            if d == 0:
                zero_count += 1

        if len(diffs) < 10:
            return False

        mean = sum(diffs) / len(diffs)
        var = sum((x - mean) ** 2 for x in diffs)

        if var == 0:
            acf1 = -1.0
        else:
            cov = sum(
                (diffs[i] - mean) * (diffs[i - 1] - mean)
                for i in range(1, len(diffs))
            )
            acf1 = cov / var

        zero_rate = zero_count / len(diffs)
        net_move = window[-1] - window[0]

        return (
            acf1 < self.ACF1_THRESHOLD
            and zero_rate > self.ZERO_RATE_THRESHOLD
            and net_move > self.NET_MOVE_THRESHOLD
        )

    # =====================================================
    # TAKER ALPHA
    # =====================================================

    def taker_alpha(
        self,
        best_bid: int,
        best_ask: int,
        bid_vol: int,
        ask_vol: int,
        position: int,
        data: Dict[str, Any],
    ) -> List[Order]:

        orders: List[Order] = []
        mids = data.get("mid", [])

        if len(mids) < self.FAIR_WINDOW:
            return orders

        fair = sum(mids[-self.FAIR_WINDOW:]) / self.FAIR_WINDOW

        # Buy cheap ask
        if best_ask < fair - self.TAKER_THRESHOLD and position < self.LIMIT:
            size = min(self.TAKER_SIZE, ask_vol, self.LIMIT - position)
            if size > 0:
                orders.append(Order(self.PRODUCT, best_ask, size))

        # Sell rich bid
        if best_bid > fair + self.TAKER_THRESHOLD and position > -self.LIMIT:
            size = min(self.TAKER_SIZE, bid_vol, self.LIMIT + position)
            if size > 0:
                orders.append(Order(self.PRODUCT, best_bid, -size))

        return orders

    # =====================================================
    # DEFENSIVE MARKET MAKING
    # =====================================================

    def defensive_mm(
        self,
        best_bid: int,
        best_ask: int,
        bid_vol: int,
        ask_vol: int,
        position: int,
        spread: int,
        base_size: int,
        max_size: int,
        min_spread: int,
    ) -> List[Order]:

        orders: List[Order] = []

        if spread < min_spread:
            return orders

        buy_price = best_bid + 1
        sell_price = best_ask - 1

        inv_ratio = position / self.LIMIT

        # Long inventory -> avoid buying, encourage selling
        if inv_ratio > 0.3:
            buy_price -= 2
            sell_price -= 1

        # Short inventory -> avoid selling, encourage buying
        elif inv_ratio < -0.3:
            buy_price += 1
            sell_price += 2

        buy_price = min(buy_price, best_ask - 1)
        sell_price = max(sell_price, best_bid + 1)

        if buy_price >= sell_price:
            return orders

        size = base_size

        if spread >= min_spread + 2:
            size += 1

        size = min(size, max_size)

        buy_size = size
        sell_size = size

        if position > 0:
            buy_size = max(0, buy_size - 1)
            sell_size = min(max_size, sell_size + 1)

        elif position < 0:
            sell_size = max(0, sell_size - 1)
            buy_size = min(max_size, buy_size + 1)

        # Hard inventory protection
        if position >= 7:
            buy_size = 0
            sell_size = max(sell_size, 2)

        elif position <= -7:
            sell_size = 0
            buy_size = max(buy_size, 2)

        buy_size = min(buy_size, ask_vol, self.LIMIT - position)
        sell_size = min(sell_size, bid_vol, self.LIMIT + position)

        if buy_size > 0:
            orders.append(Order(self.PRODUCT, buy_price, buy_size))

        if sell_size > 0:
            orders.append(Order(self.PRODUCT, sell_price, -sell_size))

        return orders

    # =====================================================
    # FLATTEN AFTER KILL SWITCH
    # =====================================================

    def flatten_position(
        self,
        od: OrderDepth,
        position: int,
    ) -> List[Order]:

        orders: List[Order] = []

        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)

        bid_vol = int(od.buy_orders[best_bid])
        ask_vol = -int(od.sell_orders[best_ask])

        if position > 0:
            size = min(position, bid_vol)
            if size > 0:
                orders.append(Order(self.PRODUCT, best_bid, -size))

        elif position < 0:
            size = min(-position, ask_vol)
            if size > 0:
                orders.append(Order(self.PRODUCT, best_ask, size))

        return orders

    # =====================================================
    # DATA STORAGE
    # =====================================================

    def update_history(self, mid: float, data: Dict[str, Any]) -> None:
        if "mid" not in data:
            data["mid"] = []

        data["mid"].append(mid)

        if len(data["mid"]) > self.HISTORY_LIMIT:
            data["mid"] = data["mid"][-self.HISTORY_LIMIT:]

    def load_data(self, trader_data: str) -> Dict[str, Any]:
        if trader_data:
            try:
                return json.loads(trader_data)
            except Exception:
                return {}
        return {}
