"""
Decision helper for live SPY scalping paper trading (research/paper_trade_runbook.md).

This script does NOT call any broker/data API itself — the agent running the runbook
fetches live bars/quotes via the Robinhood MCP tools, writes them to a CSV, and calls this
script to get a same signal decision the backtests used (imported from spy_backtest_lib so
paper trading can't drift from what was backtested).

Usage:
    python3 paper_trade_engine.py signal <bars_csv>
        -> JSON: {"side": "long"|"short"|null, "vwap":, "ema9":, "ema21":, "rsi":, "relvol":,
                  "close":, "stop":, "target":, "strike": int, "in_session_window": bool}
"""
import json
import sys
from datetime import datetime, time as dtime
from spy_backtest_lib import load_bars, compute_indicators, in_session_window, signals

TARGET_R = 1.5


def get_signal(csv_path):
    bars = load_bars(csv_path)
    if len(bars) < 3:
        return {"side": None, "reason": "not enough bars yet"}

    ema9, ema21, rsi, vwap, relvol = compute_indicators(bars)
    i = len(bars) - 1
    b = bars[i]

    side, count = signals(i, bars, ema9, ema21, rsi, vwap, relvol)
    in_window = in_session_window(b["ts"])

    result = {
        "ts": b["ts"].isoformat(),
        "close": b["close"],
        "vwap": round(vwap[i], 4),
        "ema9": round(ema9[i], 4),
        "ema21": round(ema21[i], 4),
        "rsi": round(rsi[i], 2) if rsi[i] is not None else None,
        "relvol": round(relvol[i], 2) if relvol[i] is not None else None,
        "in_session_window": in_window,
        "side": None,
        "signal_count": count,
    }

    if not in_window or side is None:
        return result

    entry_price = b["close"]
    if side == "long":
        stop = min(vwap[i], ema21[i]) - 0.02
        risk_per_share = entry_price - stop
    else:
        stop = max(vwap[i], ema21[i]) + 0.02
        risk_per_share = stop - entry_price

    if risk_per_share <= 0.01:
        return result  # degenerate stop, no trade

    target = entry_price + TARGET_R * risk_per_share if side == "long" else entry_price - TARGET_R * risk_per_share
    result.update({
        "side": side,
        "entry_price": entry_price,
        "stop": round(stop, 4),
        "target": round(target, 4),
        "strike": round(entry_price),
    })
    return result


def check_exit(side, stop, target, current_high, current_low, current_close, now_iso, market_close_hhmm="16:00"):
    now = datetime.fromisoformat(now_iso)
    hh, mm = map(int, market_close_hhmm.split(":"))
    session_over = now.time() >= dtime(hh, mm)

    hit_stop = (current_low <= stop) if side == "long" else (current_high >= stop)
    hit_target = (current_high >= target) if side == "long" else (current_low <= target)

    if hit_stop:
        return {"exit": True, "reason": "stop", "exit_price": stop}
    if hit_target:
        return {"exit": True, "reason": "target", "exit_price": target}
    if session_over:
        return {"exit": True, "reason": "eod", "exit_price": current_close}
    return {"exit": False}


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "signal":
        print(json.dumps(get_signal(sys.argv[2]), indent=2))
    elif cmd == "check_exit":
        # side stop target high low close now_iso
        args = sys.argv[2:]
        side, stop, target, high, low, close, now_iso = args[0], float(args[1]), float(args[2]), float(args[3]), float(args[4]), float(args[5]), args[6]
        print(json.dumps(check_exit(side, stop, target, high, low, close, now_iso), indent=2))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
