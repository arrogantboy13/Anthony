# Handoff — prediction markets / BTC 15-minute
*Written 2026-09-09 for a session picking this up cold.*

## Status: research only. Nothing is running.
- **No allocation.** `research/ledger.md` lists this strategy as research-only with $0 committed.
- **No automation.** No cron, no scheduled task, no state file for this strategy. The only
  workflow in the repo (`.github/workflows/spy-paper-trading.yml`) belongs to the *SPY* strategy
  and is unrelated.
- **No orders, ever, without an explicit instruction.** Paper vs. live is the account owner's
  call and is made explicitly — never inferred from context, and never a default.
- Every script here reads public market data on demand and places nothing.

## The question that was asked
"When do I click Up vs Down on Kalshi's 15-minute BTC contracts (`KXBTC15M`), and can it be
autonomous?" The owner had been buying around $0.30 and selling around $0.50 manually.

## The answer, with what backs it
**No tradeable directional edge was found.** Six independent angles, all tested against 200
settled windows (~3,000 minute-by-minute observations, 2026-09-04 → 09-06):

| Angle | Result |
|---|---|
| Directional, hold to settlement | market calibrated to **$0.0009/contract** |
| Momentum / fade scalps | −6c chasing; fading a sharp drop nets ~0 |
| Take-profit grid (the owner's actual trade) | **48 of 48 cells negative** |
| Home-built fair-value model | **not more accurate than the market** |
| Strike-ladder arbitrage | **0 violations in 23,800 strike pairs** |
| Market making | +0.21c gross vs **7.8c/fill adverse selection** |

Cost to trade: ~2.4c/contract holding to settlement, ~4.9c round-tripping. The market is
priced by automated makers quoting off the CF Benchmarks BRTI feed.

Full write-up: `research/btc-15min-strategy.md`. General playbook:
`research/prediction-market-strategy.md`.

## The one lead that is NOT disproven
**Maker rebate + a slow-moving market.** Polymarket US *rebates* makers (Θ = −0.0125) where
Kalshi charges them (Θ = +0.0175) — worth $0.015 per round turn, taking the gross margin from
+0.21c to +1.21c. That is still short of the 7.8c adverse selection measured on a 15-minute
BTC contract, but the rebate is a *fixed credit* while adverse selection is a property of how
informed the flow is. Those are independent, so the untested combination is a rebate venue
plus a market where informed flow is rare — the opposite of a 15-minute crypto coin flip.

**Blocked on:** Polymarket US market data returns **401** without an account, so their spreads
and liquidity are unmeasured. A better fee schedule on a wider book is not an improvement.

**Cheapest next test that needs no account:** run the same adverse-selection measurement
(`btc15m_market_making.py`) against Kalshi's *weekly or monthly* series instead of 15-minute
ones. That isolates the single variable that moved the needle.

## Methodological traps — please do not re-learn these the hard way
Each of these produced a confident, wrong, profitable-looking result during the original work:

1. **Sample drift fakes edges.** "Always buy NO" showed +4c/contract. Split by day it tracked
   BTC's direction and *lost* money on the day BTC rose. **Always split by day, and prefer the
   two-sided test** (EV_yes + EV_no must equal −(spread + both fees) in a calibrated market)
   because it is drift-neutral by construction.
2. **Cluster by window, not by observation.** 15 minute-bars from one window are ONE price
   path. Effective n is ~200, not ~3,000. Clustered incorrectly, the fair-value model looked
   significantly better than the market; bootstrapped over windows the CI was [−0.0004,
   +0.0160] and included zero.
3. **A stale price feed manufactures edge.** Using the last completed 1-minute candle as spot
   (a few minutes old, ~$35 off) produced a confident **17-point** "edge" against a correctly
   priced market. Near the money **$1.90 of spot error = one probability point.** Always use a
   live ticker. Cross-exchange basis among BRTI constituents was measured at **$23.69** at one
   instant — 12.5 points, five times the entire edge budget.
4. **Mids manufacture mean reversion.** Measuring a prior move and a forward move on the same
   mid series creates negative autocorrelation via bid-ask bounce, overstating the "bounce"
   about threefold. Use executable ask/bid.
5. **No exit rule can fix a fairly-priced entry.** A fairly-priced contract is a martingale, so
   every stopping rule has EV zero before costs. Take-profit levels only trade win-rate against
   loss-size. This is why all 48 grid cells were negative and why optimizing the exit is a dead
   end — only a mispriced *entry* can generate edge.

## Scripts (stdlib only, no auth, no orders)
```
btc15m_fair_value.py            live screen; de-biased, gated on measured model error
btc15m_calibration_backtest.py  reproduces the calibration result from Kalshi's public API
btc15m_model_calibration.py     measures the model's bias/noise vs the market + bootstrap CI
btc15m_market_making.py         spread capture vs adverse selection, with venue comparison
prediction_market_edge.py       general fee/EV/Kelly/arb/de-vig math
```
`btc15m_fair_value.py` carries two constants measured by `btc15m_model_calibration.py`
(`MODEL_BIAS = -0.0542`, `RESIDUAL_SD = 0.1307`). **They drift as new windows settle — re-run
the calibration script rather than trusting them.** The signal gate requires an edge to clear
trading cost, the fee-plus-buffer floor, *and* the model's own noise band; it will almost never
open, which is correct behavior against an efficient market. An earlier version without that
gate emitted a confident one-sided "signal" every few minutes, all of them phantom.

## Data notes
- Kalshi market data is open, no auth: `api.elections.kalshi.com/trade-api/v2`.
- The default `/markets` listing is dominated by dead auto-generated parlay shards with no
  quotes. Filter by `series_ticker` to get real markets.
- `liquidity_dollars` reads `0.0000` even on active markets — use bid/ask *sizes* for depth.
- Per-minute price history: `/series/{s}/markets/{ticker}/candlesticks?period_interval=1`.
