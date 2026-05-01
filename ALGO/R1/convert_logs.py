#!/usr/bin/env python3
"""Convert backtester tick/fill logs into the Prosperity .log JSON format
that prosperity.equirag.com can parse."""

import json
import re
import uuid
import os

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
OUTPUT_FILE = os.path.join(LOGS_DIR, "prosperity_format.log")

# Product short names -> full names used in file prefixes
PRODUCT_MAP = {
    "ACO": "ASH_COATED_OSMIUM",
    "IPR": "INTARIAN_PEPPER_ROOT",
}
PRODUCTS = list(PRODUCT_MAP.keys())       # ["ACO", "IPR"]
FULL_NAMES = list(PRODUCT_MAP.values())   # full names for listings
DAYS = [-2, -1, 0]

# Tick logs use per-day timestamps (0-999900).
# Fill logs use absolute timestamps: day -2 → 0+, day -1 → 1_000_000+, day 0 → 2_000_000+.
DAY_OFFSETS = {-2: 0, -1: 1_000_000, 0: 2_000_000}


# ── Parse tick logs ──────────────────────────────────────────────────────────

def parse_tick_log(filepath):
    """Parse a tick log file, return list of dicts with order-book data per tick."""
    rows = []
    with open(filepath) as f:
        lines = f.readlines()

    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            continue
        parts = stripped.split("│")
        if len(parts) < 5:
            continue
        ts_str = parts[0].strip()
        if not ts_str.isdigit():
            continue
        ts = int(ts_str)

        # Bid side: parts[1] has "Bid3 BV3  Bid2 BV2  Bid1 BV1"
        bid_tokens = parts[1].split()
        # Ask side: parts[2] has "Ask1 AV1  Ask2 AV2  Ask3 AV3"
        ask_tokens = parts[2].split()
        # Mid/spread: parts[3] has "Mid Spread BidTot AskTot"
        mid_tokens = parts[3].split()
        # Trades: parts[4]
        trades_str = parts[4].strip()

        # Parse bids: tokens come in pairs (price, vol), right-to-left = bid3,bid2,bid1
        bids = []  # will be [(price, vol), ...] ordered bid1 (best) first
        for i in range(0, len(bid_tokens), 2):
            bids.append((int(bid_tokens[i]), int(bid_tokens[i + 1])))
        bids.reverse()  # now bid1 is first (best bid)

        # Parse asks: tokens come in pairs, left-to-right = ask1,ask2,ask3
        asks = []
        for i in range(0, len(ask_tokens), 2):
            asks.append((int(ask_tokens[i]), int(ask_tokens[i + 1])))

        mid = float(mid_tokens[0]) if mid_tokens else 0.0

        # Parse trades
        tick_trades = []
        if trades_str:
            for t in trades_str.split(","):
                t = t.strip()
                m = re.match(r"(\d+)@(\d+)", t)
                if m:
                    tick_trades.append((int(m.group(1)), int(m.group(2))))

        rows.append({
            "ts": ts,
            "bids": bids,   # [(price,vol), ...] best first, up to 3
            "asks": asks,
            "mid": mid,
            "trades": tick_trades,
        })
    return rows


# ── Parse fill logs ──────────────────────────────────────────────────────────

def parse_fill_log(filepath):
    """Parse a backtest fill log, return list of fill dicts.

    Fill timestamps are absolute (day offset already applied).
    We store both the absolute ts and the day for indexing.
    """
    fills = []
    with open(filepath) as f:
        lines = f.readlines()

    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            continue
        parts = stripped.split("│")
        if len(parts) < 5:
            continue
        # parts[0] = "   1        700   -2"
        tokens0 = parts[0].split()
        if len(tokens0) < 3 or not tokens0[0].isdigit():
            continue
        abs_ts = int(tokens0[1])
        day = int(tokens0[2])
        # Per-day timestamp = abs_ts - day_offset
        rel_ts = abs_ts - DAY_OFFSETS[day]
        # parts[1] = " BUY    6    9991"
        side_tokens = parts[1].split()
        side = side_tokens[0]      # BUY or SELL
        qty = int(side_tokens[1])
        price = int(side_tokens[2])

        fills.append({
            "abs_ts": abs_ts,
            "rel_ts": rel_ts,
            "day": day,
            "side": side,
            "qty": qty,
            "price": price,
        })
    return fills


# ── Build activitiesLog ──────────────────────────────────────────────────────

def build_activities_log(tick_data, fill_data):
    """Build the semicolon-delimited activitiesLog CSV string."""
    header = ("day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;"
              "bid_volume_2;bid_price_3;bid_volume_3;ask_price_1;ask_volume_1;"
              "ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;"
              "profit_and_loss")
    lines = [header]

    # PnL state per product (carries across days)
    pnl_state = {}
    for prefix in PRODUCTS:
        pnl_state[prefix] = {"cash": 0.0, "pos": 0}

    # Index fills by (prefix, day, rel_ts)
    fill_index = {}
    for prefix in PRODUCTS:
        for fill in fill_data.get(prefix, []):
            key = (prefix, fill["day"], fill["rel_ts"])
            fill_index.setdefault(key, []).append(fill)

    for day in DAYS:
        all_ts = set()
        for prefix in PRODUCTS:
            for row in tick_data.get(prefix, {}).get(day, []):
                all_ts.add(row["ts"])

        for ts in sorted(all_ts):
            for prefix in PRODUCTS:
                full_name = PRODUCT_MAP[prefix]
                rows = tick_data.get(prefix, {}).get(day, [])
                row = None
                for r in rows:
                    if r["ts"] == ts:
                        row = r
                        break
                if row is None:
                    continue

                # Apply fills at this tick
                for fill in fill_index.get((prefix, day, ts), []):
                    if fill["side"] == "BUY":
                        pnl_state[prefix]["cash"] -= fill["price"] * fill["qty"]
                        pnl_state[prefix]["pos"] += fill["qty"]
                    else:
                        pnl_state[prefix]["cash"] += fill["price"] * fill["qty"]
                        pnl_state[prefix]["pos"] -= fill["qty"]

                pnl = pnl_state[prefix]["cash"] + pnl_state[prefix]["pos"] * row["mid"]

                b = row["bids"]
                bp1 = b[0][0] if len(b) > 0 else ""
                bv1 = b[0][1] if len(b) > 0 else ""
                bp2 = b[1][0] if len(b) > 1 else ""
                bv2 = b[1][1] if len(b) > 1 else ""
                bp3 = b[2][0] if len(b) > 2 else ""
                bv3 = b[2][1] if len(b) > 2 else ""

                a = row["asks"]
                ap1 = a[0][0] if len(a) > 0 else ""
                av1 = a[0][1] if len(a) > 0 else ""
                ap2 = a[1][0] if len(a) > 1 else ""
                av2 = a[1][1] if len(a) > 1 else ""
                ap3 = a[2][0] if len(a) > 2 else ""
                av3 = a[2][1] if len(a) > 2 else ""

                fields = [
                    day, ts, full_name,
                    bp1, bv1, bp2, bv2, bp3, bv3,
                    ap1, av1, ap2, av2, ap3, av3,
                    row["mid"], pnl,
                ]
                lines.append(";".join(str(f) for f in fields))

    return "\n".join(lines)


# ── Build tradeHistory ───────────────────────────────────────────────────────

def build_trade_history(fill_data):
    """Build the tradeHistory list of dicts (uses absolute timestamps)."""
    trades = []
    for prefix in PRODUCTS:
        full_name = PRODUCT_MAP[prefix]
        for fill in fill_data.get(prefix, []):
            buyer = "SUBMISSION" if fill["side"] == "BUY" else ""
            seller = "SUBMISSION" if fill["side"] == "SELL" else ""
            trades.append({
                "timestamp": fill["abs_ts"],
                "buyer": buyer,
                "seller": seller,
                "symbol": full_name,
                "currency": "XIRECS",
                "price": float(fill["price"]),
                "quantity": fill["qty"],
            })
    trades.sort(key=lambda t: t["timestamp"])
    return trades


# ── Build logs (lambdaLog entries) ───────────────────────────────────────────

def build_logs(tick_data, fill_data):
    """Build the logs array with one entry per timestamp (absolute timestamps)."""
    listings = [[name, name, 1] for name in FULL_NAMES]

    # Index fills by (prefix, day, rel_ts)
    fill_index = {}
    for prefix in PRODUCTS:
        for fill in fill_data.get(prefix, []):
            key = (prefix, fill["day"], fill["rel_ts"])
            fill_index.setdefault(key, []).append(fill)

    position = {name: 0 for name in FULL_NAMES}
    own_trades_pending = {name: [] for name in FULL_NAMES}

    log_entries = []

    for day in DAYS:
        offset = DAY_OFFSETS[day]
        all_ts = set()
        for prefix in PRODUCTS:
            for row in tick_data.get(prefix, {}).get(day, []):
                all_ts.add(row["ts"])

        for ts in sorted(all_ts):
            abs_ts = ts + offset

            # Build order depths from tick data
            order_depths = {}
            for prefix in PRODUCTS:
                full_name = PRODUCT_MAP[prefix]
                rows = tick_data.get(prefix, {}).get(day, [])
                row = None
                for r in rows:
                    if r["ts"] == ts:
                        row = r
                        break
                if row is None:
                    continue

                buy_orders = {}
                for price, vol in row["bids"]:
                    buy_orders[str(price)] = vol
                sell_orders = {}
                for price, vol in row["asks"]:
                    sell_orders[str(price)] = -vol

                order_depths[full_name] = [buy_orders, sell_orders]

            # own_trades reported at this tick = fills from PREVIOUS tick
            reported_own_trades = []
            for name in FULL_NAMES:
                reported_own_trades.extend(own_trades_pending[name])
                own_trades_pending[name] = []

            state = [
                abs_ts,
                "",                     # traderData
                listings,
                order_depths,
                reported_own_trades,
                [],                     # market_trades
                {k: v for k, v in position.items() if v != 0},
                [{}, {}],               # observations
            ]

            orders = []
            conversions = 0
            trader_data_out = ""

            lambda_log = json.dumps([state, orders, conversions, trader_data_out, ""])

            log_entries.append({
                "sandboxLog": "",
                "lambdaLog": lambda_log,
                "timestamp": abs_ts,
            })

            # Process fills at this tick for NEXT tick's own_trades
            for prefix in PRODUCTS:
                full_name = PRODUCT_MAP[prefix]
                for fill in fill_index.get((prefix, day, ts), []):
                    buyer = "SUBMISSION" if fill["side"] == "BUY" else ""
                    seller = "SUBMISSION" if fill["side"] == "SELL" else ""
                    own_trades_pending[full_name].append(
                        [full_name, float(fill["price"]), fill["qty"], buyer, seller, abs_ts]
                    )
                    if fill["side"] == "BUY":
                        position[full_name] += fill["qty"]
                    else:
                        position[full_name] -= fill["qty"]

    return log_entries


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Load tick data
    tick_data = {}
    for prefix in PRODUCTS:
        tick_data[prefix] = {}
        for day in DAYS:
            filename = f"{prefix}_day_{day}_tick_log.txt"
            filepath = os.path.join(LOGS_DIR, filename)
            if os.path.exists(filepath):
                tick_data[prefix][day] = parse_tick_log(filepath)
                print(f"  Loaded {filename}: {len(tick_data[prefix][day])} ticks")

    # Load fill data
    fill_data = {}
    for prefix in PRODUCTS:
        filename = f"{prefix}_backtest_fills.txt"
        filepath = os.path.join(LOGS_DIR, filename)
        if os.path.exists(filepath):
            fill_data[prefix] = parse_fill_log(filepath)
            print(f"  Loaded {filename}: {len(fill_data[prefix])} fills")

    print("\nBuilding activitiesLog...")
    activities_log = build_activities_log(tick_data, fill_data)
    activity_lines = activities_log.count("\n")
    print(f"  {activity_lines} lines")

    print("Building tradeHistory...")
    trade_history = build_trade_history(fill_data)
    print(f"  {len(trade_history)} trades")

    print("Building logs (lambdaLog entries)...")
    logs = build_logs(tick_data, fill_data)
    print(f"  {len(logs)} entries")

    result = {
        "submissionId": str(uuid.uuid4()),
        "activitiesLog": activities_log,
        "logs": logs,
        "tradeHistory": trade_history,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f)

    size_mb = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
    print(f"\nWrote {OUTPUT_FILE}")
    print(f"  Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
