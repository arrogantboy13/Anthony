"""
Backtest for the SPY scalping playbook (research/SPY-scalping-strategy.md) — SHARES version.

Implements the playbook's rules directly:
- Session windows: 9:30-10:30 and 15:00-16:00 ET only
- Entry: >=3 of 4 confluence signals (VWAP reclaim, EMA9/21 cross, RSI(14) momentum, relative volume)
- Stop: VWAP/EMA invalidation (not a fixed dollar amount)
- Target: 1.5x risk full exit (partial-at-1x is approximated as a single full exit at avg of the two)
- Max 1 trade/day (cash-account / PDT-safe model, per SPY-scalping-strategy.md section 5a)
- Position sizing: capital-capped fractional shares — min(risk budget / stop distance, balance / entry price)

Data: SPY 5-minute bars, regular session, pulled via Robinhood get_equity_historicals.
Trades shares (not options) — see backtest_spy_options_scalping.py for the leveraged version,
which is the one that actually matches how this strategy will be paper-traded at $1,500.

Ledger: this backtest is a simulation only — it does NOT write to research/ledger.md.
Only real paper fills against the $1,500 allocation belong in that ledger.
"""
from spy_backtest_lib import load_bars, compute_indicators, in_session_window, signals
from datetime import datetime

CSV_PATH = "/tmp/claude-0/-home-user-Anthony/1280a2cf-4441-5288-aa7f-39b2f8521d62/scratchpad/spy_5min.csv"

STARTING_EQUITY = 1_500.0  # matches the SPY scalping allocation in research/ledger.md
RISK_PCT = 0.01
TARGET_R = 1.5
MAX_TRADES_PER_DAY = 1  # cash-account / PDT-safe model — see strategy doc section 5a
MAX_CONSEC_LOSSES = 2


def run_backtest(bars):
    ema9, ema21, rsi, vwap, relvol = compute_indicators(bars)
    n = len(bars)

    equity = STARTING_EQUITY
    trades = []
    open_pos = None
    day_trade_count = {}
    day_consec_losses = {}
    halted_days = set()

    for i in range(n):
        b = bars[i]
        day = b["ts"].date()
        day_trade_count.setdefault(day, 0)
        day_consec_losses.setdefault(day, 0)

        if open_pos:
            side = open_pos["side"]
            hit_stop = (b["low"] <= open_pos["stop"]) if side == "long" else (b["high"] >= open_pos["stop"])
            hit_target = (b["high"] >= open_pos["target"]) if side == "long" else (b["low"] <= open_pos["target"])
            session_over = b["ts"].time() >= datetime(2000, 1, 1, 16, 0).time()

            exit_price = reason = None
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
                day_consec_losses[day] = day_consec_losses[day] + 1 if pnl < 0 else 0
                open_pos = None
                if day_consec_losses[day] >= MAX_CONSEC_LOSSES:
                    halted_days.add(day)

        if open_pos is not None or day in halted_days or day_trade_count[day] >= MAX_TRADES_PER_DAY:
            continue
        if not in_session_window(b["ts"]):
            continue

        side, count = signals(i, bars, ema9, ema21, rsi, vwap, relvol)
        if side is None:
            continue

        entry_price = b["close"]
        if side == "long":
            stop = min(vwap[i], ema21[i]) - 0.02
            risk_per_share = entry_price - stop
        else:
            stop = max(vwap[i], ema21[i]) + 0.02
            risk_per_share = stop - entry_price

        if risk_per_share <= 0.01:
            continue

        target = entry_price + TARGET_R * risk_per_share if side == "long" else entry_price - TARGET_R * risk_per_share
        risk_dollars = equity * RISK_PCT
        risk_based_shares = risk_dollars / risk_per_share
        capital_capped_shares = equity / entry_price
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

    eq = STARTING_EQUITY
    peak = eq
    max_dd = 0.0
    for t in trades:
        eq += t["pnl"]
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
