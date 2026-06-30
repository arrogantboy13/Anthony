# SPY Scalping — Paper Trading Runbook
*Follow this exactly when triggered. Mode: PAPER ONLY — never place a real order.*

This runs on a cron schedule during the playbook's two session windows (9:30–10:30 and
15:00–16:00 ET, weekdays). Each firing is a fresh check: read state, manage any open
position, look for a new entry if flat, write state + ledger, commit + push.

## 0. Setup
- Read `research/paper_trade_state.json` for current state (open position, balance, day trade counts, halted days).
- Get current time. If today is a weekend or a US market holiday, or current time is outside 9:30–16:00 ET (full regular session), stop — log nothing, no-op.
- Note: this runbook is invoked roughly every ~12 minutes across the *entire* regular session, not just the two entry windows — an open position must be monitored continuously (stop/target/EOD can trigger any time), even though **new** entries only happen inside 9:30–10:30 or 15:00–16:00. That window restriction is enforced by `paper_trade_engine.py signal`'s `in_session_window` flag in step 2, not by this setup step.

## 1. If a position is open (`open_position` is not null)
- Fetch a live SPY quote (`get_equity_quotes`) and a live quote for the open option contract (`get_option_quotes` using the stored `instrument_id`).
- Reconstruct today's intraday high/low since the position was entered is not trivial from a single quote — instead use `get_equity_historicals` for SPY, `interval=5minute`, `start_time` = today's market open, `end_time` = now, to get today's bars including the most recent one's high/low/close.
- Save those bars to a CSV (e.g. `/tmp/.../scratchpad/spy_today.csv`) and run:
  `python3 research/paper_trade_engine.py check_exit <side> <stop> <target> <last_bar_high> <last_bar_low> <last_bar_close> <now_iso>`
- If `exit: true`:
  - Determine the **option** exit price from the live option quote's `mark_price` at this moment (not the underlying stop/target price — those are the underlying-price triggers that decide *when* to exit, but the P&L is realized in the option premium).
  - pnl = (exit_option_mark - open_position.entry_premium) * 100 * open_position.contracts
  - Update `balance` in state file by `pnl`.
  - Append a row to `research/ledger.md`'s SPY scalping trade table: date, side, strike, entry premium, exit premium, pnl, exit reason, new balance.
  - Set `open_position` to null.
  - Increment `day_consec_losses[today]` if pnl < 0, else reset to 0. If it hits 2, add today to `halted_days`.
  - Save state file.
  - Commit and push both files to `claude/spy-scalping-sfsyj2`.
- If `exit: false`: do nothing further this cycle (state unchanged).

## 2. If flat (`open_position` is null)
- Skip if today is in `halted_days`, or `day_trade_count[today] >= 1` (PDT/cash-account-safe: max 1 round trip/day — see SPY-scalping-strategy.md section 5a).
- Fetch SPY 5-min bars going back **2 calendar days** (not just today) to now (`get_equity_historicals`, regular bounds) — this pre-seeds RSI(14), EMA9/21, and relative-volume with enough prior bars that indicators are valid from today's open. Without this, RSI takes 14 bars (~70 min) to initialize, which means the entire 9:30–10:30 morning window fires no signals from a cold start.
- Save to CSV (include all bars returned — the prior-session bars are warm-up only; signal decisions are still gated by today's date and `in_session_window`).
- Run `python3 research/paper_trade_engine.py signal <csv_path>`.
- If `side` is null: no entry this cycle, stop.
- If `side` is set:
  - Strike = the `strike` field returned (nearest $1, ATM).
  - Determine expiration: same-day (0DTE) if SPY has a contract expiring today; otherwise use the nearest upcoming expiration (`get_option_chains` for SPY, pick the closest `expiration_dates` entry that is today or later).
  - `get_option_instruments` for that chain/expiration/strike/type (`call` if side="long", `put` if side="short") to get the `instrument_id`.
  - `get_option_quotes` for that instrument to get the live `mark_price` (this is the real entry premium — do NOT use the Black-Scholes model from the backtest scripts; this is live paper trading against real quotes).
  - Contracts = 1 (per strategy doc, capped at $1,500 allocation). Skip the trade if `mark_price * 100 > balance * 0.35` (too large a bite — log as skipped, no position opened).
  - Otherwise, open the position: store in `open_position` — side, strike, instrument_id, entry_premium (mark_price), contracts, entry_ts, the `stop`/`target` (underlying price levels from the signal output).
  - Increment `day_trade_count[today]`.
  - Save state file. Commit and push.

## 3. Always
- Update `last_check_utc` in the state file to now, even on a no-op cycle that found nothing to do — this is also a good signal the cron job is alive and not silently broken. Commit and push after this saves too, if anything changed.
- If any tool call fails (e.g. market data unavailable), do not guess or fabricate a price — log the failure in your response and leave state untouched for the next cycle to retry.

## Reminders
- This is paper trading: never call `place_option_order` or `place_equity_order` for this strategy.
- `research/backtest_spy_options_scalping.py`'s Black-Scholes pricer is for backtesting only — live paper trades must use real `get_option_quotes` data, which is the entire point of moving to paper trading instead of trusting the BS model.
- The ledger (`research/ledger.md`) is the human-readable source of truth for P&L; the state JSON is just the machine-readable working memory between cron firings.
