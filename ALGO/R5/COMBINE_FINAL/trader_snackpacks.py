import math
from typing import Any, Dict, List

from datamodel import Order, OrderDepth, Symbol, TradingState


class Trader:
    PRODUCTS = [
        "SNACKPACK_CHOCOLATE",
        "SNACKPACK_VANILLA",
        "SNACKPACK_PISTACHIO",
        "SNACKPACK_STRAWBERRY",
        "SNACKPACK_RASPBERRY",
    ]

    LIMITS = {
        "SNACKPACK_CHOCOLATE":  10,
        "SNACKPACK_VANILLA":    10,
        "SNACKPACK_PISTACHIO":  10,
        "SNACKPACK_STRAWBERRY": 10,
        "SNACKPACK_RASPBERRY":  10,
    }

    # =====================================================
    # PARAMETERS
    # =====================================================

    # Window must stay small enough that the encoded traderData fits the
    # 50,000-char submission cap. With two histories using the *2-int compact
    # encoding below, ~3000 values each lands around 39k chars.
    BASKET_WINDOW = 3000
    # The platform preview only runs 1000 iterations, so this must be well
    # under 1000 or no trades fire on the preview at all.
    MIN_BASKET_HISTORY = 100

    ENTRY_Z = 2.0
    EXIT_Z = 0.0
    PANIC_Z = 4.0

    STAT_ARB_BASE_SIZE = 4
    STAT_ARB_MAX_SIZE = 10

    SIGMA_FLOOR = 50.0

    MICROPRICE_EDGE_MULT = 0.15
    IMBALANCE_EDGE_MULT = 1.5

    # Spread A (axis B): RASP - CHOC - VAN.
    # CHOC and VAN return-corr -0.916, so CHOC+VAN cancels axis A and the
    # basket is a near-pure axis-B trade.
    BASKET_A_LEGS = {
        "SNACKPACK_RASPBERRY": +1,
        "SNACKPACK_CHOCOLATE": -1,
        "SNACKPACK_VANILLA":   -1,
    }
    BASKET_A_ANCHOR = "SNACKPACK_RASPBERRY"

    # Spread B (axis B): STR + PIS. Return-corr +0.913, integer 1:1.
    # Shares no products with basket A, so position limits never compete.
    BASKET_B_LEGS = {
        "SNACKPACK_STRAWBERRY": +1,
        "SNACKPACK_PISTACHIO":  +1,
    }
    BASKET_B_ANCHOR = "SNACKPACK_STRAWBERRY"

    def run(self, state: TradingState):
        orders: Dict[Symbol, List[Order]] = {p: [] for p in self.PRODUCTS}
        conversions = 0

        data = self.load_data(state.traderData)

        mids = {}
        best_bids = {}
        best_asks = {}
        microprices = {}
        imbalances = {}

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
            microprices[product] = self.microprice(depth)
            imbalances[product] = self.imbalance(depth)

        # =====================================================
        # STAT ARB: BASKET A (RASP - CHOC - VAN)
        # =====================================================

        z_a = None

        if all(p in mids for p in self.BASKET_A_LEGS):
            self.update_basket_a_history(data, mids)
            z_a = self.compute_basket_a_z(data)

            if z_a is not None:
                self.manage_basket_a_position(
                    state=state,
                    orders=orders,
                    best_bids=best_bids,
                    best_asks=best_asks,
                    microprices=microprices,
                    imbalances=imbalances,
                    z=z_a,
                )

        # =====================================================
        # STAT ARB: BASKET B (STR + PIS)
        # =====================================================

        z_b = None

        if all(p in mids for p in self.BASKET_B_LEGS):
            self.update_basket_b_history(data, mids)
            z_b = self.compute_basket_b_z(data)

            if z_b is not None:
                self.manage_basket_b_position(
                    state=state,
                    orders=orders,
                    best_bids=best_bids,
                    best_asks=best_asks,
                    microprices=microprices,
                    imbalances=imbalances,
                    z=z_b,
                )

        orders = {k: v for k, v in orders.items() if v}

        trader_data = self._encode_state(data)

        return orders, conversions, trader_data

    # =====================================================
    # DATA
    # =====================================================

    def load_data(self, trader_data: str) -> Dict[str, Any]:
        return self._decode_state(trader_data)

    # Compact encoding: mids are half-integers, so basket sums/diffs are too.
    # *2 makes them exact ints; comma-separated raw with pipe between histories
    # keeps the blob well under the 50k traderData cap.
    def _encode_state(self, data: Dict[str, Any]) -> str:
        a = ",".join(str(int(round(v * 2))) for v in data.get("basket_a_history", []))
        b = ",".join(str(int(round(v * 2))) for v in data.get("basket_b_history", []))
        return a + "|" + b

    def _decode_state(self, trader_data: str) -> Dict[str, Any]:
        empty = {"basket_a_history": [], "basket_b_history": []}

        if not trader_data:
            return empty

        parts = trader_data.split("|")

        if len(parts) != 2:
            return empty

        try:
            a = [int(t) / 2.0 for t in parts[0].split(",") if t]
            b = [int(t) / 2.0 for t in parts[1].split(",") if t]
        except ValueError:
            return empty

        return {"basket_a_history": a, "basket_b_history": b}

    def update_basket_a_history(self, data: Dict[str, Any], mids: Dict[str, float]) -> None:
        value = sum(sign * mids[p] for p, sign in self.BASKET_A_LEGS.items())

        data["basket_a_history"].append(value)

        if len(data["basket_a_history"]) > self.BASKET_WINDOW:
            data["basket_a_history"] = data["basket_a_history"][-self.BASKET_WINDOW:]

    def update_basket_b_history(self, data: Dict[str, Any], mids: Dict[str, float]) -> None:
        value = sum(sign * mids[p] for p, sign in self.BASKET_B_LEGS.items())

        data["basket_b_history"].append(value)

        if len(data["basket_b_history"]) > self.BASKET_WINDOW:
            data["basket_b_history"] = data["basket_b_history"][-self.BASKET_WINDOW:]

    def compute_basket_a_z(self, data: Dict[str, Any]):
        return self._z_score(data.get("basket_a_history", []))

    def compute_basket_b_z(self, data: Dict[str, Any]):
        return self._z_score(data.get("basket_b_history", []))

    def _z_score(self, hist: List[float]):
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

    def manage_basket_a_position(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        microprices: Dict[str, float],
        imbalances: Dict[str, float],
        z: float,
    ) -> None:

        # Flatten if signal has decayed back to the mean.
        if abs(z) <= self.EXIT_Z:
            self.flatten_basket_a(state=state, orders=orders, best_bids=best_bids, best_asks=best_asks)
            return

        # If z is not extreme, do not open new stat arb positions.
        if abs(z) < self.ENTRY_Z:
            return

        # If z is too extreme, reduce size because it may be regime break.
        if abs(z) > self.PANIC_Z:
            base_size = 1
        else:
            base_size = min(
                self.STAT_ARB_MAX_SIZE,
                max(1, int(self.STAT_ARB_BASE_SIZE * abs(z) / self.ENTRY_Z)),
            )

        # z > 0: basket rich  -> sell RASP, buy CHOC + VAN
        if z > self.ENTRY_Z:
            self.open_short_basket_a(
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
                microprices=microprices,
                imbalances=imbalances,
                base_size=base_size,
            )

        # z < 0: basket cheap -> buy RASP, sell CHOC + VAN
        elif z < -self.ENTRY_Z:
            self.open_long_basket_a(
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
                microprices=microprices,
                imbalances=imbalances,
                base_size=base_size,
            )

    def manage_basket_b_position(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        microprices: Dict[str, float],
        imbalances: Dict[str, float],
        z: float,
    ) -> None:

        if abs(z) <= self.EXIT_Z:
            self.flatten_basket_b(state=state, orders=orders, best_bids=best_bids, best_asks=best_asks)
            return

        if abs(z) < self.ENTRY_Z:
            return

        if abs(z) > self.PANIC_Z:
            base_size = 1
        else:
            base_size = min(
                self.STAT_ARB_MAX_SIZE,
                max(1, int(self.STAT_ARB_BASE_SIZE * abs(z) / self.ENTRY_Z)),
            )

        # z > 0: STR + PIS rich  -> sell both
        if z > self.ENTRY_Z:
            self.open_short_basket_b(
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
                microprices=microprices,
                imbalances=imbalances,
                base_size=base_size,
            )

        # z < 0: STR + PIS cheap -> buy both
        elif z < -self.ENTRY_Z:
            self.open_long_basket_b(
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
                microprices=microprices,
                imbalances=imbalances,
                base_size=base_size,
            )

    # ----- Basket A open/close -----

    def open_short_basket_a(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        microprices: Dict[str, float],
        imbalances: Dict[str, float],
        base_size: int,
    ) -> None:
        # Short basket: legs with sign +1 are SOLD, legs with sign -1 are BOUGHT.
        for product, sign in self.BASKET_A_LEGS.items():
            self._send_leg_order(
                product=product,
                direction=-sign,
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
                microprices=microprices,
                imbalances=imbalances,
                base_size=base_size,
            )

    def open_long_basket_a(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        microprices: Dict[str, float],
        imbalances: Dict[str, float],
        base_size: int,
    ) -> None:
        for product, sign in self.BASKET_A_LEGS.items():
            self._send_leg_order(
                product=product,
                direction=+sign,
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
                microprices=microprices,
                imbalances=imbalances,
                base_size=base_size,
            )

    def flatten_basket_a(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
    ) -> None:
        for product in self.BASKET_A_LEGS:
            self._send_flatten_order(
                product=product,
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
            )

    # ----- Basket B open/close -----

    def open_short_basket_b(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        microprices: Dict[str, float],
        imbalances: Dict[str, float],
        base_size: int,
    ) -> None:
        for product, sign in self.BASKET_B_LEGS.items():
            self._send_leg_order(
                product=product,
                direction=-sign,
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
                microprices=microprices,
                imbalances=imbalances,
                base_size=base_size,
            )

    def open_long_basket_b(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        microprices: Dict[str, float],
        imbalances: Dict[str, float],
        base_size: int,
    ) -> None:
        for product, sign in self.BASKET_B_LEGS.items():
            self._send_leg_order(
                product=product,
                direction=+sign,
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
                microprices=microprices,
                imbalances=imbalances,
                base_size=base_size,
            )

    def flatten_basket_b(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
    ) -> None:
        for product in self.BASKET_B_LEGS:
            self._send_flatten_order(
                product=product,
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
            )

    # ----- Order primitives -----

    def _send_leg_order(
        self,
        product: str,
        direction: int,           # +1 = buy this leg, -1 = sell this leg
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        microprices: Dict[str, float],
        imbalances: Dict[str, float],
        base_size: int,
    ) -> None:
        pos = state.position.get(product, 0)
        limit = self.LIMITS[product]

        signal = self.micro_signal(
            mid=(best_bids[product] + best_asks[product]) / 2,
            microprice=microprices[product],
            imbalance=imbalances[product],
        )

        size = base_size

        # Microstructure confirmation: nudge size by +1 if microstructure
        # agrees with our basket-leg direction.
        if direction > 0 and signal > 0:
            size += 1
        elif direction < 0 and signal < 0:
            size += 1

        if direction > 0:
            buy_capacity = limit - pos
            qty = min(size, buy_capacity)
            if qty > 0:
                orders[product].append(Order(product, best_asks[product], qty))
        else:
            sell_capacity = limit + pos
            qty = min(size, sell_capacity)
            if qty > 0:
                orders[product].append(Order(product, best_bids[product], -qty))

    def _send_flatten_order(
        self,
        product: str,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
    ) -> None:
        pos = state.position.get(product, 0)

        if pos > 0:
            orders[product].append(Order(product, best_bids[product], -pos))
        elif pos < 0:
            orders[product].append(Order(product, best_asks[product], -pos))

    # =====================================================
    # MICROSTRUCTURE
    # =====================================================

    def best_bid_ask(self, depth: OrderDepth):
        if not depth.buy_orders or not depth.sell_orders:
            return None, None

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())

        return best_bid, best_ask

    def imbalance(self, depth: OrderDepth) -> float:
        if not depth.buy_orders or not depth.sell_orders:
            return 0.0

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())

        bid_vol = abs(depth.buy_orders[best_bid])
        ask_vol = abs(depth.sell_orders[best_ask])

        total = bid_vol + ask_vol

        if total == 0:
            return 0.0

        return (bid_vol - ask_vol) / total

    def microprice(self, depth: OrderDepth) -> float:
        if not depth.buy_orders or not depth.sell_orders:
            return 0.0

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())

        bid_vol = abs(depth.buy_orders[best_bid])
        ask_vol = abs(depth.sell_orders[best_ask])

        total = bid_vol + ask_vol

        if total == 0:
            return (best_bid + best_ask) / 2

        return (best_ask * bid_vol + best_bid * ask_vol) / total

    def micro_signal(self, mid: float, microprice: float, imbalance: float) -> int:
        signal = 0

        if microprice > mid:
            signal += 1
        elif microprice < mid:
            signal -= 1

        if imbalance > 0.5:
            signal += 1
        elif imbalance < -0.5:
            signal -= 1

        return signal
