import json
import math
from typing import Any, Dict, List

from datamodel import Order, OrderDepth, Symbol, TradingState


class Trader:
    PRODUCTS = [
        "PEBBLES_L",
        "PEBBLES_M",
        "PEBBLES_S",
        "PEBBLES_XL",
        "PEBBLES_XS",
    ]

    LIMITS = {
        "PEBBLES_L": 10,
        "PEBBLES_M": 10,
        "PEBBLES_S": 10,
        "PEBBLES_XL": 10,
        "PEBBLES_XS": 10,
    }

    # =====================================================
    # PARAMETERS
    # =====================================================

    RATIO_WINDOW = 300
    MIN_RATIO_HISTORY = 60

    ENTRY_Z = 2.0
    EXIT_Z = 0.45
    PANIC_Z = 4.0

    STAT_ARB_BASE_SIZE = 1
    STAT_ARB_MAX_SIZE = 4

    XS_MM_SIZE = 1
    S_MM_SIZE = 2
    LM_MM_SIZE = 1

    MICROPRICE_EDGE_MULT = 0.15
    IMBALANCE_EDGE_MULT = 1.5

    XS_SHORT_DRIFT_SKEW = -1.5
    INVENTORY_SKEW = 0

    MIN_SPREAD_TO_MM = {
        "PEBBLES_XS": 9,
        "PEBBLES_S": 11,
        "PEBBLES_L": 13,
        "PEBBLES_M": 13,
        "PEBBLES_XL": 17,
    }

    BASKET_PRODUCTS = [
        "PEBBLES_L",
        "PEBBLES_M",
        "PEBBLES_S",
        "PEBBLES_XS",
    ]

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
        # STAT ARB: BASKET VS XL
        # =====================================================

        z = None

        if all(p in mids for p in self.PRODUCTS):
            self.update_ratio_history(data, mids)
            z = self.compute_basket_z(data)

            if z is not None:
                self.manage_stat_arb_position(
                    state=state,
                    orders=orders,
                    mids=mids,
                    best_bids=best_bids,
                    best_asks=best_asks,
                    microprices=microprices,
                    imbalances=imbalances,
                    z=z,
                )

        # =====================================================
        # MARKET MAKING
        # =====================================================

        for product in self.PRODUCTS:
            if product not in mids:
                continue

            # Do not MM XL heavily. XL is mainly hedge/stat arb leg.
            if product == "PEBBLES_XL":
                continue

            self.market_make(
                state=state,
                orders=orders,
                product=product,
                mid=mids[product],
                best_bid=best_bids[product],
                best_ask=best_asks[product],
                microprice=microprices[product],
                imbalance=imbalances[product],
            )

        trader_data = json.dumps(data, separators=(",", ":"))

        return orders, conversions, trader_data

    # =====================================================
    # DATA
    # =====================================================

    def load_data(self, trader_data: str) -> Dict[str, Any]:
        if trader_data:
            try:
                data = json.loads(trader_data)
            except Exception:
                data = {}
        else:
            data = {}

        if "basket_ratios" not in data:
            data["basket_ratios"] = []

        return data

    def update_ratio_history(self, data: Dict[str, Any], mids: Dict[str, float]) -> None:
        basket = (
            mids["PEBBLES_L"]
            + mids["PEBBLES_M"]
            + mids["PEBBLES_S"]
            + mids["PEBBLES_XS"]
        ) / 4

        xl = mids["PEBBLES_XL"]

        if xl <= 0:
            return

        ratio = basket / xl

        data["basket_ratios"].append(ratio)

        if len(data["basket_ratios"]) > self.RATIO_WINDOW:
            data["basket_ratios"] = data["basket_ratios"][-self.RATIO_WINDOW:]

    def compute_basket_z(self, data: Dict[str, Any]):
        hist = data.get("basket_ratios", [])

        if len(hist) < self.MIN_RATIO_HISTORY:
            return None

        current = hist[-1]
        mean = sum(hist) / len(hist)
        variance = sum((x - mean) ** 2 for x in hist) / len(hist)
        std = math.sqrt(variance)

        if std <= 1e-9:
            return None

        return (current - mean) / std

    # =====================================================
    # STAT ARB LOGIC
    # =====================================================

    def manage_stat_arb_position(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        mids: Dict[str, float],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        microprices: Dict[str, float],
        imbalances: Dict[str, float],
        z: float,
    ) -> None:

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

        # z > 0:
        # basket rich vs XL -> sell basket, buy XL
        if z > self.ENTRY_Z:
            self.open_short_basket_long_xl(
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
                mids=mids,
                microprices=microprices,
                imbalances=imbalances,
                base_size=base_size,
            )

        # z < 0:
        # basket cheap vs XL -> buy basket, sell XL
        elif z < -self.ENTRY_Z:
            self.open_long_basket_short_xl(
                state=state,
                orders=orders,
                best_bids=best_bids,
                best_asks=best_asks,
                mids=mids,
                microprices=microprices,
                imbalances=imbalances,
                base_size=base_size,
            )

    def open_short_basket_long_xl(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        mids: Dict[str, float],
        microprices: Dict[str, float],
        imbalances: Dict[str, float],
        base_size: int,
    ) -> None:

        # First check XL capacity.
        xl_pos = state.position.get("PEBBLES_XL", 0)
        xl_buy_capacity = self.LIMITS["PEBBLES_XL"] - xl_pos

        if xl_buy_capacity <= 0:
            return

        basket_trade_count = 0

        for product in self.BASKET_PRODUCTS:
            pos = state.position.get(product, 0)
            sell_capacity = self.LIMITS[product] + pos

            if sell_capacity <= 0:
                continue

            signal = self.micro_signal(
                mid=mids[product],
                microprice=microprices[product],
                imbalance=imbalances[product],
            )

            size = base_size

            # If microstructure confirms downside, slightly increase.
            if signal < 0:
                size += 1

            size = min(size, sell_capacity)

            if size > 0:
                orders[product].append(Order(product, best_bids[product], -size))
                basket_trade_count += size

        # Hedge with XL, but limit is 10, so keep it small.
        xl_size = min(xl_buy_capacity, max(1, basket_trade_count // 2))

        if xl_size > 0:
            orders["PEBBLES_XL"].append(
                Order("PEBBLES_XL", best_asks["PEBBLES_XL"], xl_size)
            )

    def open_long_basket_short_xl(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        best_bids: Dict[str, int],
        best_asks: Dict[str, int],
        mids: Dict[str, float],
        microprices: Dict[str, float],
        imbalances: Dict[str, float],
        base_size: int,
    ) -> None:

        xl_pos = state.position.get("PEBBLES_XL", 0)
        xl_sell_capacity = self.LIMITS["PEBBLES_XL"] + xl_pos

        if xl_sell_capacity <= 0:
            return

        basket_trade_count = 0

        for product in self.BASKET_PRODUCTS:
            pos = state.position.get(product, 0)
            buy_capacity = self.LIMITS[product] - pos

            if buy_capacity <= 0:
                continue

            signal = self.micro_signal(
                mid=mids[product],
                microprice=microprices[product],
                imbalance=imbalances[product],
            )

            size = base_size

            # If microstructure confirms upside, slightly increase.
            if signal > 0:
                size += 1

            size = min(size, buy_capacity)

            if size > 0:
                orders[product].append(Order(product, best_asks[product], size))
                basket_trade_count += size

        xl_size = min(xl_sell_capacity, max(1, basket_trade_count // 2))

        if xl_size > 0:
            orders["PEBBLES_XL"].append(
                Order("PEBBLES_XL", best_bids["PEBBLES_XL"], -xl_size)
            )

    # =====================================================
    # MARKET MAKING
    # =====================================================

    def market_make(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        product: str,
        mid: float,
        best_bid: int,
        best_ask: int,
        microprice: float,
        imbalance: float,
    ) -> None:

        spread = best_ask - best_bid

        if spread < self.MIN_SPREAD_TO_MM[product]:
            return

        pos = state.position.get(product, 0)
        limit = self.LIMITS[product]

        if product == "PEBBLES_XS":
            size = self.XS_MM_SIZE
        elif product == "PEBBLES_S":
            size = self.S_MM_SIZE
        else:
            size = self.LM_MM_SIZE

        fair = mid

        # Microprice skew: if microprice above mid, fair moves up.
        fair += self.MICROPRICE_EDGE_MULT * (microprice - mid)

        # Imbalance skew: positive imbalance means more bid pressure.
        fair += self.IMBALANCE_EDGE_MULT * imbalance

        # XS has persistent downward drift, so lean slightly short.
        if product == "PEBBLES_XS":
            fair += self.XS_SHORT_DRIFT_SKEW

        # Inventory skew: if long, lower fair to encourage selling.
        fair -= self.INVENTORY_SKEW * pos

        bid_price = int(math.floor(fair - spread * 0.35))
        ask_price = int(math.ceil(fair + spread * 0.35))

        # Keep inside/near the current book but avoid crazy crossing.
        bid_price = min(bid_price, best_bid + 1)
        ask_price = max(ask_price, best_ask - 1)

        buy_qty = min(size, limit - pos)
        sell_qty = min(size, limit + pos)

        if buy_qty > 0:
            orders[product].append(Order(product, bid_price, buy_qty))

        if sell_qty > 0:
            orders[product].append(Order(product, ask_price, -sell_qty))

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