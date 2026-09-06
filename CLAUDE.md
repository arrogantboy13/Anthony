# Anthony — trading research repo

Personal research repo for rule-based trading strategies. Everything here is
**research and paper trading**. No live orders are placed from this repo.

## Layout

| Path | What it is |
|---|---|
| `research/ledger.md` | Master ledger — allocations, balances, and settled P&L across strategies. Human-readable source of truth. |
| `research/SPY-scalping-strategy.md` | The SPY scalping playbook: session windows, kill conditions, entry confluence, risk rules, and the $1,500-account constraints (§5a). |
| `research/paper_trade_runbook.md` | Step-by-step procedure for one paper-trading cycle. Follow it exactly when running a check. |
| `research/paper_trade_state.json` | Machine-readable working memory between cycles: open position, balance, day-trade counts, halted days, `last_check_utc`. |
| `research/paper_trade_engine.py` | Signal and exit logic. CLI: `signal <csv> [date]`, `check_exit <side> <stop> <target> <high> <low> <close> <now_iso>`. Prints JSON. |
| `research/spy_backtest_lib.py` | Shared indicator/backtest helpers. |
| `research/backtest_spy_scalping.py` | Share-based backtest. |
| `research/backtest_spy_options_scalping.py` | Options backtest with a Black-Scholes pricer. **Backtest only.** |
| `research/WEN-wendys-analysis.md` | Standalone equity research. No allocation sized. |
| `.github/workflows/spy-paper-trading.yml` | Cron that runs the runbook via `claude-code-action` during session windows. |

## Rules

- **Paper only.** Never call `place_equity_order`, `place_option_order`,
  `place_crypto_order`, or `exercise_option` for anything in this repo. These are
  denied in `.claude/settings.json`; if a live strategy is ever added, that is an
  explicit decision to make first, not a permission to route around.
- **Never fabricate market data.** If a quote or historical fetch fails, say so and
  leave state untouched for the next cycle. A guessed price silently corrupts the
  ledger.
- **Live paper trades use real quotes**, not the Black-Scholes model in
  `backtest_spy_options_scalping.py`. That pricer exists for backtesting; using it
  for a paper fill defeats the point of paper trading.
- **P&L is realized in option premium**, not in the underlying. The stop/target are
  underlying-price levels that decide *when* to exit; the fill price comes from the
  option's live `mark_price`.
- **Ledger and state move together.** After any fill, update
  `research/paper_trade_state.json` and append the row to `research/ledger.md` in the
  same commit.
- **Account constraints bind.** At the $1,500 allocation this runs as a cash account:
  max 1 round trip per day, halt for the session after 2 consecutive losses. See
  `SPY-scalping-strategy.md` §5a before changing any sizing or frequency rule.

## Running things

```bash
# Entry signal from a CSV of 5-min bars (pass today's ET date so prior-session
# warm-up bars can't trigger a false entry)
python3 research/paper_trade_engine.py signal /path/to/bars.csv 2026-09-06

# Exit check for an open position. now_iso must be ET, not UTC — check_exit
# compares its clock time against the 16:00 market close directly, so a "Z"
# timestamp reads as past the close and forces a spurious EOD exit.
python3 research/paper_trade_engine.py check_exit long 6412.50 6431.00 \
  6433.10 6428.40 6431.80 2026-09-06T15:24:00
```

No dependencies to install, no build, no test suite. Scratch CSVs go in a temp
directory, never in the repo.

## Local and web sessions

This file and `.claude/settings.json` are committed, so a local `claude` session
opened in this directory and a Claude Code web session on this repo load the same
context and the same permission rules. Keep repo-wide conventions here; put personal
overrides in `.claude/settings.local.json`, which is gitignored.
