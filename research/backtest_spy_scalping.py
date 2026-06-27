"""
Backtest for the SPY scalping playbook (research/SPY-scalping-strategy.md).

Implements the playbook's rules directly:
- Session windows: 9:30-10:30 and 15:00-16:00 ET only
- Entry: >=3 of 4 confluence signals (VWAP reclaim, EMA9/21 cross, RSI(14) momentum, relative volume)
- Stop: VWAP/EMA invalidation (not a fixed dollar amount)
- Target: 1.5x risk full exit (partial-at-1x is approximated as a single full exit at avg of the two)
- Max 1 trade/day (cash-account / PDT-safe model, per SPY-scalping-strategy.md section 5a)
- Position sizing: capital-capped fractional shares — min(risk budget / stop distance, balance / entry price)

Data: SPY 5-minute bars, regular session, pulled via Robinhood get_equity_historicals.
Trades shares (not options) to isolate the entry/exit logic from theta/IV noise -
see README notes in SPY-scalping-strategy.md for why that's a simplification.

Ledger: this backtest is a simulation only — it does NOT write to research/ledger.md.
Only real (paper or live) fills against the $1,500 allocation belong in that ledger.
"""
import csv
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CSV_PATH = "/tmp/claude-0/-home-user-Anthony/1280a2cf-4441-5288-aa7f-39b2f8521d62/scratchpad/spy_5min.csv"

STARTING_EQUITY = 1_500.0  # matches the SPY scalping allocation in research/ledger.md
RISK_PCT = 0.01
TARGET_R = 1.5
MAX_TRADES_PER_DAY = 1  # cash-account / PDT-safe model — see strategy doc section 5a
MAX_CONSEC_LOSSES = 2
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

    # EMA
    def ema_series(period):
        k = 2 / (period + 1)
        out = [None] * n
        for i, c in enumerate(closes):
            if i == 0:
                out[i] = c
            else:
                out[i] = c * k + out[i - 1] * (1 - k)
        return out

    ema9 = ema_series(EMA_FAST)
    ema21 = ema_series(EMA_SLOW)

    # RSI (Wilder's, simple rolling)
    rsi = [None] * n
    gains, losses = 0.0, 0.0
    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
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

    # Session-reset VWAP and relative volume (rolling avg of trailing N bars within session)
    vwap = [None] * n
    relvol = [None] * n
    day_keys = [b["ts"].date() for b in bars]
    cum_pv, cum_vol = 0.0, 0.0
    vol_window = []
    prev_day = None
    for i, b in enumerate(bars):
        if day_keys[i] != prev_day:
            cum_pv, cum_vol = 0.0, 0.0
            vol_window = []
            prev_day = day_keys[i]
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
    if i < 2 or rsi[i] is None or relvol[i] is None:
        return None, 0
    c, c_prev = bars[i]["close"], bars[i - 1]["close"]

    long_signals = 0
    short_signals = 0

    # VWAP reclaim/reject
    if c_prev < vwap[i - 1] and c > vwap[i]:
        long_signals += 1
    if c_prev > vwap[i - 1] and c < vwap[i]:
        short_signals += 1

    # EMA cross / trend alignment
    if ema9[i] > ema21[i] and ema9[i - 1] <= ema21[i - 1]:
        long_signals += 1
    elif ema9[i] > ema21[i]:
        long_signals += 0.5
    if ema9[i] < ema21[i] and ema9[i - 1] >= ema21[i - 1]:
        short_signals += 1
    elif ema9[i] < ema21[i]:
        short_signals += 0.5

    # RSI momentum
    if rsi[i] > 50 and rsi[i] > rsi[i - 1] and rsi[i] < 70:
        long_signals += 1
    if rsi[i] < 50 and rsi[i] < rsi[i - 1] and rsi[i] > 30:
        short_signals += 1

    # Relative volume
    if relvol[i] >= RELVOL_THRESHOLD:
        long_signals += 1
        short_signals += 1  # volume confirms either direction

    if long_signals >= 3 and long_signals > short_signals:
        return "long", long_signals
    if short_signals >= 3 and short_signals > long_signals:
        return "short", short_signals
    return None, 0


def run_backtest(bars):
    ema9, ema21, rsi, vwap, relvol = compute_indicators(bars)
    n = len(bars)

    equity = STARTING_EQUITY
    trades = []
    open_pos = None  # dict: side, entry_price, entry_i, stop, target, shares
    day_trade_count = {}
    day_consec_losses = {}
    halted_days = set()

    for i in range(n):
        b = bars[i]
        day = b["ts"].date()
        day_trade_count.setdefault(day, 0)
        day_consec_losses.setdefault(day, 0)

        # Manage open position first
        if open_pos:
            side = open_pos["side"]
            hit_stop = (b["low"] <= open_pos["stop"]) if side == "long" else (b["high"] >= open_pos["stop"])
            hit_target = (b["high"] >= open_pos["target"]) if side == "long" else (b["low"] <= open_pos["target"])
            session_over = b["ts"].time() >= datetime(2000, 1, 1, 16, 0).time()

            exit_price = None
            reason = None
            if hit_stop:
                exit_price, reason = open_pos["stop"], "stop"
            elif hit_target:
                exit_price, reason = open_pos["target"], "target"
            elif session_over:
                exit_price, reason = b["close"], "eod"

            if exit_price is not None:
                pnl_per_share = (exit_price - open_pos["entry_price"]) if side == "long" else (open_pos["entry_price"] - exit_price)
                pnl = pnl_per_share * open_pos["shares"]
                equity += pnl
                trades.append({
                    "day": day, "side": side, "entry_ts": open_pos["entry_ts"], "exit_ts": b["ts"],
                    "entry": open_pos["entry_price"], "exit": exit_price, "pnl": pnl, "reason": reason,
                })
                if pnl < 0:
                    day_consec_losses[day] += 1
                else:
                    day_consec_losses[day] = 0
                open_pos = None
                if day_consec_losses[day] >= MAX_CONSEC_LOSSES:
                    halted_days.add(day)

        if open_pos is not None:
            continue
        if day in halted_days:
            continue
        if day_trade_count[day] >= MAX_TRADES_PER_DAY:
            continue
        if not in_session_window(b["ts"]):
            continue

        side, count = signals(i, bars, ema9, ema21, rsi, vwap, relvol)
        if side is None:
            continue

        entry_price = b["close"]
        if side == "long":
            stop = min(vwap[i], ema21[i]) - 0.02  # small buffer
            risk_per_share = entry_price - stop
        else:
            stop = max(vwap[i], ema21[i]) + 0.02
            risk_per_share = stop - entry_price

        if risk_per_share <= 0.01:
            continue  # degenerate stop, skip

        target = entry_price + TARGET_R * risk_per_share if side == "long" else entry_price - TARGET_R * risk_per_share
        risk_dollars = equity * RISK_PCT
        risk_based_shares = risk_dollars / risk_per_share
        capital_capped_shares = equity / entry_price  # fractional shares, no margin
        shares = round(min(risk_based_shares, capital_capped_shares), 4)
        if shares <= 0:
            continue

        open_pos = {
            "side": side, "entry_price": entry_price, "entry_ts": b["ts"],
            "stop": stop, "target": target, "shares": shares,
        }
        day_trade_count[day] += 1

    return trades, equity


def summarize(trades, final_equity):
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)
    win_rate = len(wins) / n * 100 if n else 0
    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    profit_factor = (sum(t["pnl"] for t in wins) / -sum(t["pnl"] for t in losses)) if losses and sum(t["pnl"] for t in losses) != 0 else float("inf")

    # max drawdown on equity curve
    eq = STARTING_EQUITY
    peak = eq
    max_dd = 0.0
    curve = [eq]
    for t in trades:
        eq += t["pnl"]
        curve.append(eq)
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak)

    by_reason = {}
    for t in trades:
        by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1

    days = sorted(set(t["day"] for t in trades))
    print(f"Backtest period: {days[0] if days else '-'} to {days[-1] if days else '-'} ({len(days)} trading days with trades)")
    print(f"Total trades: {n}")
    print(f"Win rate: {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"Avg win: ${avg_win:,.2f}   Avg loss: ${avg_loss:,.2f}")
    print(f"Profit factor: {profit_factor:.2f}")
    print(f"Exit reasons: {by_reason}")
    print(f"Total P&L: ${total_pnl:,.2f}")
    print(f"Starting equity: ${STARTING_EQUITY:,.2f}  Final equity: ${final_equity:,.2f}  Return: {(final_equity/STARTING_EQUITY-1)*100:.2f}%")
    print(f"Max drawdown: {max_dd*100:.2f}%")


if __name__ == "__main__":
    bars = load_bars(CSV_PATH)
    trades, final_equity = run_backtest(bars)
    summarize(trades, final_equity)
    print()
    print("Trade log:")
    for t in trades:
        print(f"  {t['day']} {t['side']:5s} entry={t['entry']:.2f} exit={t['exit']:.2f} "
              f"pnl=${t['pnl']:.2f} ({t['reason']})")
