# Trading Ledger
*Master ledger across all active strategies — last updated 2026-06-27*

Each strategy gets a **fixed sub-allocation**: its own capital slice, tracked independently. Strategies do not borrow from each other's allocation. Update this file after every trade (or batch of trades) that settles.

## Allocations

| Strategy | Allocation | Current balance | Mode | Status |
|---|---|---|---|---|
| SPY scalping | $1,500.00 | $1,500.00 | **Paper** | Active — no real orders are placed; all fills are simulated against live quotes |
| WEN (Wendy's) | Not yet allocated | — | — | Research only, no position sized |

**Paper, not live.** Every trade logged against the SPY scalping allocation below is a simulated fill — entries/exits use real-time quotes at decision time, but no real order is ever placed. Do not place live orders against this strategy without an explicit instruction to switch modes, and update the Mode column here if that ever changes.

**Total capital committed to strategies above**: $1,500.00 (SPY scalping only; WEN has no allocation until a position is explicitly sized).

## SPY scalping ledger detail

Starting balance: **$1,500.00**

| Date | Trade | Side | Entry | Exit | P&L | Balance after |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | $1,500.00 |

*(No live or paper trades logged yet — backtest results are tracked separately in the backtest script output, not in this ledger, since backtests aren't real fills against this balance.)*

## Rules for updating this file
- Only log trades that actually executed (paper or live) against the strategy's real allocation — not backtest simulations.
- After each fill, append a row and recompute the running balance.
- If a strategy's balance drops to a level where its position-sizing rules no longer produce a viable trade size (see each strategy doc's "Account size & constraints" section), pause that strategy and note it in the Status column instead of forcing undersized trades.
- When a new strategy gets capital allocated, add a row to the Allocations table before any trade is placed.
