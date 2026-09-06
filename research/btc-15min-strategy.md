# BTC 15-Minute Up/Down — What the Data Says
*Kalshi `KXBTC15M` · analysis run 2026-09-06*

The short version: **I could not find a directional edge, and I can show you why the ones
that look real aren't.** This document is the evidence, the pricing model, and — if you're
going to trade these anyway — the rules that make the economics least bad.

## 1. The contract
`KXBTC15M`, "BTC price up in next 15 mins?", one market per 15-minute window:

> If the simple average of the sixty seconds of CF Benchmarks' BRTI before 11:45 AM EDT is
> at least the simple average of the sixty seconds of BRTI before 11:30 AM EDT, the market
> resolves to Yes.

Both endpoints are **60-second averages of an index**, not spot prints on any one exchange.
That detail does more damage to a home-built model than anything else here (§5). Each window's
target is the prior window's settlement value, so at the open the contract is a true coin flip
and prices ~50c. Liquidity is real: the window I sampled had 1.28M contracts of volume and
330k open interest.

## 2. Headline: this is a calibrated market with a toll
Across **200 settled windows (3,000 minute-by-minute observations), 2026-09-04 → 09-06**, all reproducible with `research/btc15m_calibration_backtest.py`:

| Measure | Value |
|---|---|
| Windows resolving YES | **96 / 200 (48.0%)** |
| EV of buying YES at ask, held to settlement | −$0.0501 / contract |
| EV of buying NO at ask, held to settlement | +$0.0097 / contract |
| **Sum of both sides** | **−$0.0404** |
| Structural cost (spread + both fees) | **−$0.0413** |
| **Gap = mispricing available to anyone** | **+$0.0009** |

If a market is perfectly calibrated, the two sides must sum to exactly the cost of trading:
whatever one side wins, the other loses, minus what the house takes. **The observed sum lands
within one tenth of one cent of that.** There is no systematic pricing error to harvest. The
48% YES base rate is BTC drifting down slightly over these two days, not a bias.

## 3. The trap: "buy NO is always +EV"
Bucket the data naively and buying NO looks profitable at almost every price — +4 cents per
contract in the 0.6–0.7 bucket. It is not an edge. It is the sample drifting down. Split by day:

| Day | Windows | Base rate YES | EV of buying NO |
|---|---|---|---|
| 2026-09-04 | 40 | 50.0% | **+$0.0175** |
| 2026-09-05 | 96 | 51.0% | **−$0.0097** |
| 2026-09-06 | 64 | 42.2% | **+$0.0340** |

The "edge" tracks that day's BTC direction one-for-one. On the day BTC drifted up, the same
rule lost money. **"Always buy NO" is a short BTC position wearing a strategy costume** — and
two days of data is nowhere near enough to distinguish one from the other. Any backtest of
these markets that doesn't control for realized drift will find this fake edge.

A second trap, same shape: de-drifting the data makes the final two minutes look like they
carry a +3 point signal. They don't. In the last minute prices are already pinned near 0 or 1,
so `outcome − price` is ~0 by construction, and subtracting a day-level drift correction from
a number that is structurally zero manufactures the entire "signal."

## 4. What it costs to play
Per contract, for one trader taking liquidity and holding to settlement (half-spread + fee):

| Contract price | Avg spread | Fee | **Hurdle/contract** | Max gain if right |
|---|---|---|---|---|
| 0.0–0.1 | $0.0013 | $0.0100 | **$0.0106** | $0.97 |
| 0.2–0.3 | $0.0100 | $0.0200 | **$0.0250** | $0.75 |
| 0.4–0.5 | $0.0101 | $0.0200 | **$0.0250** | $0.55 |
| 0.6–0.7 | $0.0102 | $0.0200 | **$0.0251** | $0.35 |
| 0.9–1.0 | $0.0012 | $0.0100 | **$0.0106** | $0.03 |

Two things follow. **The fee dominates the spread** (2.0c vs 0.5c half-spread), and Kalshi's
fee peaks at exactly 50c — so trading these at the money means paying the maximum possible fee
for the maximum possible uncertainty. And the spread itself widens with time left: $0.0010 in
the final minute, $0.0103 with a full 15 minutes to run.

**You need to beat a market calibrated to 0.1 cents by 2.5 cents, four times an hour.**

## 5. Why a fair-value model doesn't rescue this
The pricing is not hard. Over 15 minutes BTC drift is negligible next to volatility, so:

```
fair = Φ( (spot − target) / (σ₁ₘ · √T_eff · spot) ),  T_eff = minutes_left − 0.5
```

(`T_eff` because settlement is a 60-second average ending at the close, so the observation is
effectively centered half a minute early.) Current BTC realized vol is **σ₁ₘ = 0.0292%**, which
makes a 15-minute 1-sd move about **$90 on an $80k coin**.

That small σ is the problem. Near the money the probability curve is steepest, and
`research/btc15m_fair_value.py` reports the sensitivity directly:

> **$1.90 of spot error = 1 full probability point.**

So your edge budget of ~2.5 cents is spent by **$5 of pricing error**. Two things blow through
that instantly:

- **Stale data.** My first run used the last completed 1-minute candle as spot. It was a few
  minutes old, off by ~$35, and produced a confident **17-point "edge"** against a correctly
  priced market. Switching to a live ticker collapsed it to 3 points. That is what a naive
  model on this market feels like from the inside: it will hand you large, urgent, wrong signals.
- **Index basis.** The contract settles on BRTI, a multi-exchange index. Sampling four of its
  constituents at the same instant: Coinbase $79,689.91, Kraken $79,695.20, Bitstamp $79,693.96,
  Gemini $79,713.60 — a **$23.69 spread**. At $1.90 per point, *the disagreement between the
  exchanges the index is built from is already 12.5 points of pricing error* — five times your
  entire edge budget, before you've been wrong about anything.

Unless you are pricing off the BRTI feed itself with sub-second latency, your fair value is
noisier than the market's. The market makers quoting 1-cent spreads on 1.28M contracts have
that feed. This is not a modeling problem you can out-think; it's a data problem you'd have
to out-spend.

## 6. So — when to buy up/down?
**On a 15-minute horizon, there is no "when."** Fifteen-minute BTC returns carry essentially no
predictive structure, the market is calibrated to a tenth of a cent, and the toll is 2.5 cents
a round trip. A directional call needs to be right about 55% of the time just to break even at
mid prices, and nothing in this data suggests any rule gets you there. Four windows an hour,
96 a day, turns a small negative edge into a fast, high-variance bleed.

If you want BTC directional exposure, spot or dated options give it to you without paying a
2.5-cent-per-contract toll every 15 minutes.

## 7. If you're trading them anyway
In rough order of how much each one is worth:

1. **Post, don't take.** Kalshi's maker rate is about a quarter of the taker rate — roughly
   0.44c instead of 1.75c — and a resting order earns the spread instead of paying it. This is
   the single biggest lever available and it roughly flips a −2.5c hurdle to about −0.5c. It's
   also the only structurally sound way to be in this market: you get paid for providing
   liquidity rather than paying for consuming it.
2. **Never trade at the money.** 40–60c is where the fee is maximal and the outcome is closest
   to a coin flip — the worst cell in the table for both reasons at once.
3. **Batch into one order.** The fee rounds up to the cent *per order*, which is why the table
   above shows $0.02 at 1 contract where the un-rounded rate is $0.0175. Ten separate
   1-contract orders pay the rounding ten times.
4. **Use a live ticker, never a candle close** — and treat any signal above ~10 points as
   evidence your feed is broken, not that you found something. Run
   `python3 research/btc15m_fair_value.py` and read `dollars_per_probability_point` before
   trusting any edge it reports.
5. **Size tiny and cap the session.** Quarter-Kelly on an edge you can't verify is still
   quarter of a guess: cap any single window at ~2% of the sleeve and stop after a fixed number
   of windows per day. The 96-windows-a-day cadence is what turns a thin negative edge into a
   fast one.

## 8. What would change the answer
- **A BRTI or direct multi-exchange feed** with sub-second latency — removes the §5 basis
  problem, which is the binding constraint, not the model.
- **A venue with a flat or lower fee at mid prices** — the 1.75c fee at 50c is most of the toll.
- **A much larger sample.** 200 windows over two days cannot separate a 1-cent edge from drift;
  the §3 trap shows exactly how that fails. Several thousand windows across varied regimes
  would be the minimum before believing any rule found here.

## 9. Reproducing this
No credentials and no scheduled jobs — Kalshi's market data API is open, and this was all
pulled on demand:

```
# the full calibration backtest — reproduces every number above
python3 research/btc15m_calibration_backtest.py --limit 200

#   underlying endpoints (open, no auth):
#   GET /trade-api/v2/markets?status=settled&series_ticker=KXBTC15M
#   GET /trade-api/v2/series/KXBTC15M/markets/{ticker}/candlesticks?period_interval=1

# live screen (fetches on demand, places no orders)
python3 research/btc15m_fair_value.py
python3 research/btc15m_fair_value.py --offline <spot> <target> <mins_left> <ask> [<bid>]
```

Fee, sizing, and threshold math is shared with the general playbook in
`research/prediction-market-strategy.md` and `research/prediction_market_edge.py`.

## Bottom line
These markets are efficiently priced by people with a better data feed than you can buy, and
they charge 2.5 cents a round trip for the privilege of guessing. The two edges that appear in
the data — "always buy NO" and the last-minute signal — are both artifacts, and I'd rather hand
you the disproof than the backtest. If you want to be in this market, be the one posting quotes,
not the one crossing them.
