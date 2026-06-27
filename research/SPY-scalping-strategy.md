# SPY Scalping Playbook
*Reusable intraday strategy — last updated 2026-06-27*

This is a rule-based playbook for scalping SPY (shares or short-dated options), not a one-off market call. Run the checklist before every entry; if any "kill" condition is true, skip the trade.

## 1. Session windows (when to scalp)
SPY scalps work best in the two highest-volume, most directional windows of the regular session (all times ET):
- **9:30–10:30** — opening range; highest volume, widest initial range, best for breakout/breakdown scalps off the first 5–15min range.
- **15:00–16:00** — power hour; institutional rebalancing flow, good for trend-continuation or reversal scalps into the close.
- **Avoid 11:30–13:30** ("lunch chop") unless a macro catalyst (FOMC, CPI, NFP, big-cap earnings) is firing — low volume, high false-breakout rate.

## 2. Kill conditions (skip the trade if any are true)
- VIX > 25 and rising sharply intraday — moves become erratic, stops get blown through.
- No clear trend on the 5-min chart in the last 30 minutes (price chopping inside a tight range with no defined high/low).
- A scheduled high-impact macro release (FOMC decision, CPI, NFP, major Fed speaker) is due within 15 minutes — wait until after the reaction settles.
- Spread on the option you'd trade is wider than ~10% of the option's mid price — slippage will eat the scalp's edge.

## 3. Entry setup (technical confluence)
Require at least 3 of these 4 to align before entering, using the 1-min or 5-min SPY chart:
1. **VWAP** — price reclaims/rejects VWAP with a clean candle close on the side you're trading (long above, short below).
2. **EMA** — 9 EMA crosses above/below 21 EMA (or price pulls back to the 9 EMA and holds in an established trend).
3. **RSI(14)** — momentum confirms direction: RSI > 50 and rising for longs, < 50 and falling for shorts. Avoid initiating longs when RSI is already > 70 (extended) or shorts when < 30, unless playing a reversal (see §4).
4. **Relative volume** — current bar/period volume is meaningfully above the recent average (≥1.5x) — confirms real participation, not a low-volume drift.

**Reversal variant**: if RSI(14) is at an extreme (>70 or <30) AND price tags a Bollinger Band extreme AND shows a rejection candle (long wick, close back inside the band), that's a mean-reversion scalp back toward VWAP/the 9 EMA instead of a breakout entry.

## 4. Trade structure
- **Shares**: simplest, no theta/IV risk. Use for window 1 (opening range) when volatility is high and you want clean directional exposure.
- **Options (0DTE or weekly)**: use ATM or 1 strike OTM in the direction of the trade for the most delta per dollar with manageable theta over a 15–45 minute hold. Avoid going more than 1–2 strikes OTM on a scalp — the extra leverage isn't worth the gamma risk if you're wrong.
- Never hold a 0DTE option scalp through a lunch lull or overnight — theta decay accelerates and the setup's thesis (intraday momentum) no longer applies.

## 5. Risk management
- **Position size**: risk no more than 0.5–1% of account equity per scalp. Scalping is a high-frequency, small-edge game — one oversized loss erases many wins.
- **Stop**: hard stop at the setup's invalidation level (e.g., back below VWAP for a long, back above the 9 EMA for a short) — not an arbitrary dollar amount. If the technical reason for the trade is gone, exit regardless of P&L.
- **Target**: scalps target 1.5–2x the initial risk; take partial profit at 1x risk and trail the rest with the 9 EMA or VWAP as a moving stop.
- **Max trades/day**: cap at 3–4 scalps. After 2 consecutive losses, stop for the session — tilt-driven overtrading is the most common way scalping accounts blow up.

## 6. Daily pre-market checklist
- [ ] Check VIX level and overnight futures gap — is today a "tradeable" volatility regime (not too quiet, not chaotic)?
- [ ] Note key levels: prior day high/low, overnight high/low, VWAP from prior session.
- [ ] Check economic calendar for releases during the session — flag kill-condition windows in advance.
- [ ] Confirm option spreads on the strikes you'd realistically trade are tight enough (use `get_option_chains` / `get_option_quotes` for SPY before the open).

## 7. Using the Robinhood scanner alongside this playbook
The scanner (`create_scan` / `run_scan`) operates across the market, not on a single symbol, so it can't replace watching SPY's own chart — but it's useful as a **regime filter**: run a scan for `FILTER_TYPE_RELATIVE_VOLUME > 1.5` combined with `FILTER_TYPE_RSI` extremes across major index-tracking/large-cap names before the session. If breadth confirms (most large caps showing the same RSI/volume signature as SPY), conviction in the SPY-specific setup goes up; if SPY is moving alone while breadth is flat, treat the move with more suspicion (lower size, tighter stop).

## Bottom line
This is a mechanical framework, not a guarantee — scalping has a low per-trade edge that depends entirely on discipline (sizing, stops, session timing) rather than any single indicator. Backtest or paper-trade the entry rules in §3 before risking size, and revisit the kill conditions in §2 every session — they're the part of this playbook most people skip and most often regret skipping.
