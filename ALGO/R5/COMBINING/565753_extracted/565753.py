import math
from typing import Any, Dict, List

from datamodel import Order, OrderDepth, Symbol, TradingState


class Trader:
    PRODUCTS = [
        "OXYGEN_SHAKE_GARLIC",
        "OXYGEN_SHAKE_MORNING_BREATH",
        "OXYGEN_SHAKE_EVENING_BREATH",
        "OXYGEN_SHAKE_CHOCOLATE",
    ]

    LIMITS = {
        "OXYGEN_SHAKE_GARLIC":         10,
        "OXYGEN_SHAKE_MORNING_BREATH": 10,
        "OXYGEN_SHAKE_EVENING_BREATH": 10,
        "OXYGEN_SHAKE_CHOCOLATE":      10,
    }

    # =====================================================
    # PARAMETERS
    # =====================================================

    # Window must stay small enough that the encoded traderData fits the
    # 50,000-char submission cap. With one history using the *2-int compact
    # encoding below, 7000 values lands around 42k chars (~5-6 chars/value).
    BASKET_WINDOW = 7000
    # The platform preview only runs 1000 iterations, so this must be well
    # under 1000 or no trades fire on the preview at all.
    MIN_BASKET_HISTORY = 50

    ENTRY_Z = 2.5
    # 0.0 is intentional: the strategy doesn't flatten at the mean — it flips
    # on the opposite |z|>=ENTRY_Z extreme, which captures the full reversion
    # round-trip. Sweeping EXIT_Z>0 across days 2/3/4 cuts PnL substantially.
    EXIT_Z = 0.0

    MAX_BASKET = 10
    SIGMA_FLOOR = 50.0
    SIZE_FLOOR = 0.7

    # Basket = GARLIC + MORNING + EVENING - CHOCO.
    # Most stationary integer-coefficient basket per notebook §11
    # (ADF p=0.0075, half-life ~867 ticks). Unit weights mean a position cap
    # of MAX_BASKET on every leg with no hedge-ratio rounding error.
    BASKET_LEGS = {
        "OXYGEN_SHAKE_GARLIC":         +1,
        "OXYGEN_SHAKE_MORNING_BREATH": +1,
        "OXYGEN_SHAKE_EVENING_BREATH": +1,
        "OXYGEN_SHAKE_CHOCOLATE":      -1,
    }
    BASKET_ANCHOR = "OXYGEN_SHAKE_GARLIC"

    def run(self, state: TradingState):
        orders: Dict[Symbol, List[Order]] = {p: [] for p in self.PRODUCTS}
        conversions = 0

        data = self.load_data(state.traderData)

        mids = {}
        best_bids = {}
        best_asks = {}

        for product in self.PRODUCTS:
            depth = state.order_depths.get(product)

            if depth is None:
                continue

            best_bid, best_ask = self.best_bid_ask(depth)

            if best_bid is None or best_ask is None:
                continue

            mids[product] = (best_bid + best_ask) / 2
            best_bids[product] = best_bid
            best_asks[product] = best_ask

        # =====================================================
        # STAT ARB: GARLIC + MORNING + EVENING - CHOCO
        # =====================================================

        if all(p in mids for p in self.BASKET_LEGS):
            self.update_basket_history(data, mids)
            z = self.compute_basket_z(data)

            if z is not None:
                self.manage_basket_position(
                    state=state,
                    orders=orders,
                    best_bids=best_bids,
                    best_asks=best_asks,
                    z=z,
                    history_len=len(data["basket_history"]),
                )

        orders = {k: v for k, v in orders.items() if v}

        trader_data = self._encode_state(data)

        return orders, conversions, trader_data

    # =====================================================
    # DATA
    # =====================================================

    def load_data(self, trader_data: str) -> Dict[str, Any]:
        return self._decode_state(trader_data)

    # Compact encoding: mids are half-integers, so the basket sum is too.
    # *2 makes them exact ints; comma-separated raw keeps the blob well under
    # the 50k traderData cap even when the window is at full capacity.
    def _encode_state(self, data: Dict[str, Any]) -> str:
        return ",".join(str(int(round(v * 2))) for v in data.get("basket_history", []))

    def _decode_state(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {"basket_history": []}

        try:
            hist = [int(t) / 2.0 for t in trader_data.split(",") if t]
        except ValueError:
            return {"basket_history": []}

        return {"basket_history": hist}

    def update_basket_history(self, data: Dict[str, Any], mids: Dict[str, float]) -> None:
        value = sum(sign * mids[p] for p, sign in self.BASKET_LEGS.items())

        data["basket_history"].append(value)

        if len(data["basket_history"]) > self.BASKET_WINDOW:
            data["basket_history"] = data["basket_history"][-self.BASKET_WINDOW:]

    def compute_basket_z(self, data: Dict[str, Any]):
        hist = data.get("basket_history", [])

        if len(hist) < self.MIN_BASKET_HISTORY:
            return None

        current = hist[-1]
        mean = sum(hist) / len(hist)
        variance = sum((x - mean) ** 2 for x in hist) / len(hist)
        std = max(math.sqrt(variance), self.SIGMA_FLOOR)

        if std <= 1e-9:
            return None

        return (current - mean) / std

    # =====================================================
    # STAT ARB LOGIC
    # =====================================================

    def manage_basket_position(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        z: float,
        history_len: int,
    ) -> None:

        # Confidence-scaled position cap with floor.
        size_fraction = min(1.0, max(self.SIZE_FLOOR, history_len / self.BASKET_WINDOW))
        max_pos = int(round(self.MAX_BASKET * size_fraction))

        cur_anchor_pos = state.position.get(self.BASKET_ANCHOR, 0)
        target_basket = cur_anchor_pos

        # z >= +ENTRY_Z: basket rich  -> short the basket
        if z >= self.ENTRY_Z:
            target_basket = -max_pos

        # z <= -ENTRY_Z: basket cheap -> long the basket
        elif z <= -self.ENTRY_Z:
            target_basket = max_pos

        # Flatten if the signal has decayed back to the mean.
        elif abs(z) <= self.EXIT_Z:
            target_basket = 0

        for product, sign in self.BASKET_LEGS.items():
            target = target_basket * sign
            cur = state.position.get(product, 0)
            self._send_to_target(
                product=product,
                cur=cur,
                target=target,
                orders=orders,
                best_bid=best_bids[product],
                best_ask=best_asks[product],
            )

    def _send_to_target(
        self,
        product: str,
        cur: int,
        target: int,
        orders: Dict[Symbol, List[Order]],
        best_bid: int,
        best_ask: int,
    ) -> None:
        delta = target - cur

        if delta == 0:
            return

        limit = self.LIMITS[product]

        if delta > 0:
            buy_capacity = limit - cur
            qty = min(delta, buy_capacity)
            if qty > 0:
                orders[product].append(Order(product, best_ask, qty))
        else:
            sell_capacity = limit + cur
            qty = min(-delta, sell_capacity)
            if qty > 0:
                orders[product].append(Order(product, best_bid, -qty))

    # =====================================================
    # MICROSTRUCTURE
    # =====================================================

    def best_bid_ask(self, depth: OrderDepth):
        if not depth.buy_orders or not depth.sell_orders:
            return None, None

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())

        return best_bid, best_ask