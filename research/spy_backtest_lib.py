"""
Shared indicator/signal logic for the SPY scalping backtests
(backtest_spy_scalping.py = shares, backtest_spy_options_scalping.py = options).
Keeping this in one place means both backtests test the exact same entry/exit
rules from SPY-scalping-strategy.md — only the P&L model differs.
"""
import csv
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

RELVOL_LOOKBACK = 20
RELVOL_THRESHOLD = 1.5
RSI_LEN = 14
EMA_FAST = 9
EMA_SLOW = 21


def load_bars(path):
    bars = []
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            ts = datetime.fromisoformat(row["begins_at"].replace("Z", "+00:00")).astimezone(ET)
            bars.append({
                "ts": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            })
    return bars


def compute_indicators(bars):
    closes = [b["close"] for b in bars]
    n = len(bars)

    def ema_series(period):
        k = 2 / (period + 1)
        out = [None] * n
        for i, c in enumerate(closes):
            out[i] = c if i == 0 else c * k + out[i - 1] * (1 - k)
        return out

    ema9 = ema_series(EMA_FAST)
    ema21 = ema_series(EMA_SLOW)

    rsi = [None] * n
    gains, losses = 0.0, 0.0
    avg_gain = avg_loss = 0.0
    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gain, loss = max(change, 0.0), max(-change, 0.0)
        if i <= RSI_LEN:
            gains += gain
            losses += loss
            if i == RSI_LEN:
                avg_gain, avg_loss = gains / RSI_LEN, losses / RSI_LEN
                rs = avg_gain / avg_loss if avg_loss else float("inf")
                rsi[i] = 100 - 100 / (1 + rs)
        else:
            avg_gain = (avg_gain * (RSI_LEN - 1) + gain) / RSI_LEN
            avg_loss = (avg_loss * (RSI_LEN - 1) + loss) / RSI_LEN
            rs = avg_gain / avg_loss if avg_loss else float("inf")
            rsi[i] = 100 - 100 / (1 + rs)

    vwap = [None] * n
    relvol = [None] * n
    day_keys = [b["ts"].date() for b in bars]
    cum_pv = cum_vol = 0.0
    vol_window = []
    prev_day = None
    for i, b in enumerate(bars):
        if day_keys[i] != prev_day:
            cum_pv, cum_vol, vol_window, prev_day = 0.0, 0.0, [], day_keys[i]
        typical = (b["high"] + b["low"] + b["close"]) / 3
        cum_pv += typical * b["volume"]
        cum_vol += b["volume"]
        vwap[i] = cum_pv / cum_vol if cum_vol else b["close"]

        if vol_window:
            relvol[i] = b["volume"] / (sum(vol_window) / len(vol_window))
        vol_window.append(b["volume"])
        if len(vol_window) > RELVOL_LOOKBACK:
            vol_window.pop(0)

    return ema9, ema21, rsi, vwap, relvol


def in_session_window(ts):
    t = ts.time()
    return (datetime(2000, 1, 1, 9, 30).time() <= t <= datetime(2000, 1, 1, 10, 30).time()) or \
           (datetime(2000, 1, 1, 15, 0).time() <= t <= datetime(2000, 1, 1, 16, 0).time())


def signals(i, bars, ema9, ema21, rsi, vwap, relvol):
    """Return ('long'|'short'|None, count_of_confirming_signals)."""
    if i < 2 or rsi[i] is None or rsi[i - 1] is None or relvol[i] is None:
        return None, 0
    c, c_prev = bars[i]["close"], bars[i - 1]["close"]

    long_signals = short_signals = 0

    if c_prev < vwap[i - 1] and c > vwap[i]:
        long_signals += 1
    if c_prev > vwap[i - 1] and c < vwap[i]:
        short_signals += 1

    if ema9[i] > ema21[i] and ema9[i - 1] <= ema21[i - 1]:
        long_signals += 1
    elif ema9[i] > ema21[i]:
        long_signals += 0.5
    if ema9[i] < ema21[i] and ema9[i - 1] >= ema21[i - 1]:
        short_signals += 1
    elif ema9[i] < ema21[i]:
        short_signals += 0.5

    if rsi[i] > 50 and rsi[i] > rsi[i - 1] and rsi[i] < 70:
        long_signals += 1
    if rsi[i] < 50 and rsi[i] < rsi[i - 1] and rsi[i] > 30:
        short_signals += 1

    if relvol[i] >= RELVOL_THRESHOLD:
        long_signals += 1
        short_signals += 1

    if long_signals >= 3 and long_signals > short_signals:
        return "long", long_signals
    if short_signals >= 3 and short_signals > long_signals:
        return "short", short_signals
    return None, 0
