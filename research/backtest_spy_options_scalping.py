"""
Backtest for the SPY scalping playbook (research/SPY-scalping-strategy.md) — OPTIONS version.

Same entry/exit triggers as backtest_spy_scalping.py (imported from spy_backtest_lib so the
two backtests can't drift apart), but P&L is computed on a same-day ATM option premium instead
of shares — this is the version that actually matches how the strategy will be paper-traded at
$1,500, where buying calls/puts (not shares) is the only way to get meaningful size.

Option pricing model (since historical 0DTE option chains aren't available — Robinhood only
exposes the live chain, not historical snapshots):
- Black-Scholes, no dividend yield, r=4% (approx short-term risk-free rate).
- Flat IV assumption per trade, drawn from a live SPY chain pull (730 strike, 2026-06-29
  expiry, as of 2026-06-26): observed put IV 8.1%, call IV 22.1%. The wide call/put skew on a
  2-day-out contract isn't necessarily representative of true 0DTE skew, so this model uses a
  single flat IV (DEFAULT_IV, 15% — roughly the midpoint) for both calls and puts rather than
  pretend it can model the skew accurately. This is the single biggest source of error in this
  backtest: real intraday IV moves (often crushing after opens, expanding into selloffs) and
  this model does not capture that.
- Strike = nearest $1 to the entry price (ATM), same-day expiration (T = calendar time
  remaining to 16:00 ET from the bar's timestamp).
- Always a long (debit) position — buying a call on long signals, buying a put on short
  signals — so risk per trade is bounded at the premium paid, consistent with the strategy
  doc's "size to 1 contract only" rule for small accounts.

Entry/exit *decisions* still use the same underlying-price-based stop/target/EOD triggers as
the shares backtest (VWAP/EMA invalidation, 1.5R) — only the dollar P&L of each decision is
recomputed through the option pricer.

Ledger: this backtest is a simulation only — it does NOT write to research/ledger.md.
Only real paper fills against the $1,500 allocation belong in that ledger.
"""
import math
from datetime import datetime, time as dtime
from spy_backtest_lib import load_bars, compute_indicators, in_session_window, signals

CSV_PATH = "/tmp/claude-0/-home-user-Anthony/1280a2cf-4441-5288-aa7f-39b2f8521d62/scratchpad/spy_5min.csv"

STARTING_EQUITY = 1_500.0
TARGET_R = 1.5
MAX_TRADES_PER_DAY = 1
MAX_CONSEC_LOSSES = 2
MARKET_CLOSE = dtime(16, 0)
RISK_FREE_RATE = 0.04
DEFAULT_IV = 0.15  # flat assumption — see module docstring
MAX_CONTRACTS = 1  # strategy doc: size to 1 contract only at this account size
MAX_PREMIUM_FRACTION_OF_EQUITY = 0.35  # skip the trade if 1 contract would eat >35% of the account


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(S, K, T, r, sigma, is_call):
    """Black-Scholes price per share. T in years; floors at ~1 minute to avoid T=0 blowups."""
    T = max(T, 1 / (365 * 24 * 60))
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def years_to_close(ts):
    close_dt = ts.replace(hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute, second=0, microsecond=0)
    seconds_remaining = max((close_dt - ts).total_seconds(), 30)  # floor so we never hit T<=0 mid-bar
    return seconds_remaining / (365 * 24 * 60 * 60)


def run_backtest(bars, iv=DEFAULT_IV):
    ema9, ema21, rsi, vwap, relvol = compute_indicators(bars)
    n = len(bars)

    equity = STARTING_EQUITY
    trades = []
    open_pos = None
    day_trade_count = {}
    day_consec_losses = {}
    halted_days = set()
    skipped_unaffordable = 0

    for i in range(n):
        b = bars[i]
        day = b["ts"].date()
        day_trade_count.setdefault(day, 0)
        day_consec_losses.setdefault(day, 0)

        if open_pos:
            side = open_pos["side"]
            hit_stop = (b["low"] <= open_pos["stop"]) if side == "long" else (b["high"] >= open_pos["stop"])
            hit_target = (b["high"] >= open_pos["target"]) if side == "long" else (b["low"] <= open_pos["target"])
            session_over = b["ts"].time() >= MARKET_CLOSE

            exit_stock_price = reason = None
            if hit_stop:
                exit_stock_price, reason = open_pos["stop"], "stop"
            elif hit_target:
                exit_stock_price, reason = open_pos["target"], "target"
            elif session_over:
                exit_stock_price, reason = b["close"], "eod"

            if exit_stock_price is not None:
                is_call = side == "long"
                exit_premium = bs_price(exit_stock_price, open_pos["strike"], years_to_close(b["ts"]),
                                         RISK_FREE_RATE, iv, is_call)
                exit_premium = max(exit_premium, 0.0)  # options can't go negative
                pnl = (exit_premium - open_pos["entry_premium"]) * 100 * open_pos["contracts"]
                equity += pnl
                trades.append({
                    "day": day, "side": side, "entry_ts": open_pos["entry_ts"], "exit_ts": b["ts"],
                    "strike": open_pos["strike"], "entry_premium": open_pos["entry_premium"],
                    "exit_premium": exit_premium, "contracts": open_pos["contracts"],
                    "pnl": pnl, "reason": reason,
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

        entry_stock_price = b["close"]
        if side == "long":
            stop = min(vwap[i], ema21[i]) - 0.02
            risk_per_share = entry_stock_price - stop
        else:
            stop = max(vwap[i], ema21[i]) + 0.02
            risk_per_share = stop - entry_stock_price

        if risk_per_share <= 0.01:
            continue

        target = entry_stock_price + TARGET_R * risk_per_share if side == "long" else entry_stock_price - TARGET_R * risk_per_share
        strike = round(entry_stock_price)
        is_call = side == "long"
        entry_premium = bs_price(entry_stock_price, strike, years_to_close(b["ts"]), RISK_FREE_RATE, iv, is_call)

        contract_cost = entry_premium * 100
        if contract_cost <= 0 or contract_cost > equity:
            skipped_unaffordable += 1
            continue
        if contract_cost > equity * MAX_PREMIUM_FRACTION_OF_EQUITY:
            skipped_unaffordable += 1
            continue

        open_pos = {
            "side": side, "entry_ts": b["ts"], "stop": stop, "target": target,
            "strike": strike, "entry_premium": entry_premium, "contracts": MAX_CONTRACTS,
        }
        day_trade_count[day] += 1

    return trades, equity, skipped_unaffordable


def summarize(trades, final_equity, skipped, iv):
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
    print(f"Flat IV assumption: {iv*100:.0f}%  |  risk-free rate: {RISK_FREE_RATE*100:.0f}%  |  contracts/trade: {MAX_CONTRACTS}")
    print(f"Backtest period: {days[0] if days else '-'} to {days[-1] if days else '-'} ({len(days)} trading days with trades)")
    print(f"Total trades: {n}  (skipped as unaffordable/too large: {skipped})")
    print(f"Win rate: {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"Avg win: ${avg_win:,.2f}   Avg loss: ${avg_loss:,.2f}")
    print(f"Profit factor: {profit_factor:.2f}")
    print(f"Exit reasons: {by_reason}")
    print(f"Total P&L: ${total_pnl:,.2f}")
    print(f"Starting equity: ${STARTING_EQUITY:,.2f}  Final equity: ${final_equity:,.2f}  Return: {(final_equity/STARTING_EQUITY-1)*100:.2f}%")
    print(f"Max drawdown: {max_dd*100:.2f}%")


if __name__ == "__main__":
    bars = load_bars(CSV_PATH)
    trades, final_equity, skipped = run_backtest(bars)
    summarize(trades, final_equity, skipped, DEFAULT_IV)
    print()
    print("Trade log:")
    for t in trades:
        print(f"  {t['day']} {t['entry_ts'].strftime('%H:%M')} {t['side']:5s} strike={t['strike']} "
              f"entry_prem=${t['entry_premium']:.2f} exit_prem=${t['exit_premium']:.2f} "
              f"pnl=${t['pnl']:.2f} ({t['reason']})")
    print()
    print("CAVEAT: trades entered in the last ~45-60 minutes before close have entry premiums")
    print("pushed toward $0 by the flat-IV/short-T Black-Scholes model, which makes them swing")
    print("by huge multiples on small underlying moves (a known BS degeneracy near T=0, not a")
    print("real tradable edge). Real 0DTE premiums have a much flatter floor than this model")
    print("implies late in the session. Treat the aggregate return number with skepticism;")
    print("the win-rate/structure is more trustworthy than the dollar P&L until this is")
    print("validated against real paper fills (live option quotes, not modeled prices).")
