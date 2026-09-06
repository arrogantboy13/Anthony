# Prediction Market Playbook
*Reusable strategy for binary event contracts — last updated 2026-09-06*

This is a rule-based playbook for trading event contracts (Kalshi, Robinhood's prediction
markets, Polymarket US), not a set of picks. Prediction markets look easy — you just have
to be right — but the payoff structure is unforgiving: a binary contract's entire edge lives
in the gap between your probability estimate and the price, and fees eat that gap in cents,
not basis points. Run §7's checklist before every entry; if any kill condition in §4 is
true, skip the trade.

## 1. What you're actually trading
An event contract settles at **$1.00** if the event resolves YES and **$0.00** if it doesn't.
So the price *is* the market's implied probability: a contract at $0.62 is the crowd saying
"62%." Two consequences drive everything below:

- **EV is subtraction, not multiplication.** Buying YES at ask `a` when your estimate is `p`:
  EV = `p·(1−a) − (1−p)·a` = **`p − a`**. The whole game is whether your probability beats the
  price by more than costs. There is no "let it run" — max upside is fixed at `1 − a`.
- **Risk is fully prepaid.** You cannot lose more than you paid (buying) — no stop is needed
  to cap loss, which is why §6 sizes by Kelly rather than by stop distance the way the SPY
  playbook does. Selling YES / buying NO is the same trade mirrored, at price `1 − a`.
- **Time works differently.** There's no theta. A contract 3 months from resolution and one
  3 hours out have the same payoff; what differs is how much capital gets locked up to earn
  the same `p − a`, which is why §5 screens on *annualized* return for long-dated markets.

## 2. Venue and routing — the fee schedule is part of the strategy
Fees are not a rounding error here. Because the payoff is capped at $1.00, a 2-cent fee on a
contract bought at $0.95 is 40% of everything you can possibly win. The two US venues charge
on completely different shapes:

- **Kalshi (direct)** — taker fee = `ceil(0.07 × contracts × P × (1−P))` rounded up to the
  cent, charged **per order**; maker (resting, later-filled) orders are roughly a quarter of
  that rate on markets that charge them. No settlement fee, no ACH deposit/withdrawal fee.
  The `P × (1−P)` shape means the fee is proportional to variance: **cheapest at the extremes,
  most expensive at $0.50.**
- **Robinhood (Robinhood Derivatives, routed to Kalshi)** — flat **$0.02 per contract per
  side** ($0.01 commission + $0.01 exchange fee), charged on the opening leg and again on the
  closing leg. Price-independent.
- **Polymarket US** — CFTC-regulated DCM; percentage-of-premium schedule (a taker fee in the
  tens of basis points against a maker rebate), so its costs scale with notional rather than
  with variance.

Per-contract round-trip cost, and what that costs you in probability edge:

| Contract price | Kalshi taker (per contract, large order) | Robinhood round trip | Kalshi cost as % of max gain | Robinhood cost as % of max gain |
|---|---|---|---|---|
| $0.10 | $0.0063 | $0.04 | 0.7% | 4.4% |
| $0.25 | $0.0131 | $0.04 | 1.7% | 5.3% |
| $0.50 | $0.0175 | $0.04 | 3.5% | 8.0% |
| $0.75 | $0.0131 | $0.04 | 5.2% | 16.0% |
| $0.90 | $0.0063 | $0.04 | 6.3% | 40.0% |
| $0.95 | $0.0033 | $0.04 | 6.6% | **80.0%** |

**Routing rules that fall straight out of this table:**
1. **Never buy heavy favorites (>$0.85) on a flat-fee venue.** At $0.95 the round trip is 80%
   of the maximum gain — you need to be right ~4 times out of 5 just to break even on fees.
   Same trade on Kalshi direct costs a sixth of that.
2. **On Kalshi, batch into one order.** The fee rounds *up to the cent per order*, so the
   rounding is paid once per order rather than once per contract. Ten 1-contract orders at
   $0.95 pay $0.10; the same ten contracts in one order pay $0.04. Splitting an order is a
   fee decision, not just an execution one — and it hurts most at the extremes, where the
   un-rounded fee is a fraction of a cent.
3. **Post, don't cross, when the market lets you.** A resting limit order that later fills
   pays roughly a quarter of the taker rate on Kalshi (and earns a rebate on Polymarket US).
   On any market that isn't about to resolve, work the bid.

*Fee schedules change; re-verify in-app before sizing a first trade on any venue — the July
2026 Kalshi schedule and the March 2026 Polymarket US amendment are both recent revisions.*

## 3. Where the edge actually comes from
There is no technical setup here — no VWAP, no RSI. The only edge is a **better probability
estimate than the price**, or a **structural mispricing**. Four repeatable sources, best first:

### 3a. Model-vs-market on rules-based markets (primary)
Markets whose outcome is mechanically determined by a published data source, where a free,
public model already produces a probability the crowd doesn't fully price:
- **Fed target rate** — compare the contract to CME FedWatch's fed-funds-futures-implied
  probability. Any gap wider than the fee threshold in §5 on a *liquid* rate market is
  usually the contract lagging futures, not the futures being wrong.
- **Economic releases (CPI, NFP, GDP)** — nowcasts (Cleveland Fed inflation nowcast, Atlanta
  Fed GDPNow) publish continuously updated point estimates plus historical error bands; a
  point estimate + a distribution of past forecast errors *is* a probability for a
  "CPI above X%" contract. The edge window is the hours after a nowcast update and before
  the print.
- **Weather / temperature** — NWS publishes probabilistic forecasts. These markets are thin
  and low-attention, which is exactly the condition under which a public model beats a price.

### 3b. Cross-venue and cross-market disagreement
The same event trades on Kalshi, Polymarket US, and (for sports) sportsbooks. Sportsbook
odds must be **de-vigged** before comparison — a −150/+130 pair sums to 103.5% implied, so
the raw numbers overstate both sides. `prediction_market_edge.py devig` does this. A
persistent, de-vigged gap wider than the combined fee threshold is a trade on the cheap side;
if you can take both sides across venues, it's an arb (§3d) instead of a directional bet.

### 3c. Longshot bias
Prediction markets, like betting markets, systematically overprice tails: contracts at
$0.02–$0.08 resolve YES less often than their price implies, because buyers pay up for
lottery tickets. The exploitable side is **selling** those longshots (buying NO at $0.92–0.98)
— which is precisely the trade the flat-fee schedule in §2 destroys and the Kalshi schedule
leaves viable. Two hard constraints: the payoff is many small wins and rare full losses, so
§6's per-market cap is not optional, and you need enough independent markets that one
correlated cluster resolving against you doesn't take the strategy out.

### 3d. Dutch books on multi-outcome markets
On a market with mutually exclusive, exhaustive outcomes (election winner, "which range will
CPI land in"), the YES asks must sum to $1.00. When thin books drift, they sometimes sum to
less. Buying one of each locks $1.00 in payout for less than $1.00 in cost regardless of the
outcome. `prediction_market_edge.py arb` computes the net cost including fees. These are rare,
small, and short-lived — but they're the only genuinely risk-free trade in the space, and
they're worth scanning for on any multi-outcome market you're already looking at.

### Where NOT to play
Skip the headline markets — presidential elections, marquee sports games, "will X happen by
year end" on a company everyone follows. Deep liquidity and enormous attention make these the
most efficiently priced contracts on the venue, and your probability estimate is a paraphrase
of the consensus that made the price. The edge lives in **low-attention, rules-driven markets
where a public model exists and the crowd hasn't read it**.

## 4. Kill conditions (skip the trade if any are true)
- **You haven't read the settlement rules.** The single largest source of loss in this space is
  a contract that resolves on a source or definition you assumed rather than checked — which
  print, which revision, which timestamp, what happens on a tie/postponement/no-decision.
  If you can't state the exact source and cutoff that settles the contract, you don't have a
  trade, you have an opinion.
- **Bid-ask wider than your edge.** If the spread is 4 cents and your modeled edge is 5, you
  are paying most of the edge to cross. Require spread ≤ ~2 cents on the size you want, or
  work a resting bid and accept you may not get filled.
- **No resting depth at your size.** A 1-cent-wide market with 20 contracts at the touch is a
  1-cent-wide market for 20 contracts. Size to displayed depth, not to the quote.
- **Your estimate came from the market.** If your probability is "well, it's trading at 60 so
  maybe 65," there is no edge — that's anchoring, not modeling. The estimate must come from a
  source that doesn't look at the contract price.
- **Resolution is >90 days out and the edge isn't large.** Capital is locked and the annualized
  return on a 5-cent edge over 6 months is worse than it looks (§5).
- **The market is a single correlated bet you already own.** Three contracts on "Fed cuts in
  March," "Fed cuts by June," and "2-year yield below X" are one position, not three (§6).

## 5. Entry rule — the edge threshold
Buy YES at ask `a` only when your independent estimate `p` clears the price by more than fees
*plus* a margin for being wrong:

> **`p − a  ≥  fee_per_contract + 0.03`**

The 3-cent buffer is the model-error haircut. Calibration on subjective probability estimates
is poor enough that a nominal 2-cent edge is noise; 3 cents is the smallest gap that survives
a modest estimation error. In practice:

- **Kalshi, mid-priced contract ($0.50):** fee ≈ $0.0175 → require **≥ ~5 cents** of edge.
- **Robinhood, any price:** round trip $0.04 → require **≥ ~7 cents** of edge. This is why §2
  routes size to Kalshi direct.
- **Long-dated markets:** convert to annualized return before comparing. `(p − a − fee) / a`
  is the return on capital; divide by `days_to_resolution / 365`. A 5-cent edge on a $0.50
  contract resolving in 6 months is ~20% annualized — fine, but not obviously better than the
  same 5 cents captured three times in a month on short-dated markets, and it ties up the
  allocation the whole time.

Run the arithmetic rather than eyeballing it:

```
python3 research/prediction_market_edge.py edge 0.60 0.53 --venue kalshi --contracts 100
  -> net_ev_per_contract 0.0525, breakeven_probability 0.5475, tradeable true
```

## 6. Position sizing
Because loss is prepaid and capped, sizing is a bankroll problem, not a stop problem. Use
**quarter-Kelly**:

> full Kelly `f* = (p − a) / (1 − a)`, then stake `0.25 × f* × bankroll`

Quarter, not full: Kelly is optimal only if `p` is *correct*, and an overestimated `p` at full
Kelly compounds into a drawdown that never recovers. Quarter-Kelly gives up some growth for a
large cut in variance — the right trade when your inputs are estimates.

```
python3 research/prediction_market_edge.py size 0.60 0.53 500 --venue kalshi
  -> scaled_kelly_fraction 0.0266, stake $13.30, 25 contracts, max loss $13.25
```

**Hard caps on top of Kelly:**
- **≤ 5% of the strategy allocation in any single market**, even when Kelly says more. Kelly
  assumes your probability is the only uncertainty; settlement-rule risk and venue risk aren't
  in the formula.
- **≤ 15% in any one correlated theme** (all Fed-path markets are one theme; all contracts on
  a single game are one theme). Correlated positions size as one position.
- **≤ 50% of the allocation deployed at once.** Unfilled capital is the ability to take the
  next mispricing, which is the actual scarce resource in a low-frequency strategy.
- **Longshot-selling (§3c) caps at 2% per market**, since the loss is the full $0.92–0.98.

## 7. Pre-trade checklist
- [ ] Can I state the exact settlement source, cutoff time, and tie/void handling from the
      contract's own rules page? (Kill condition — no guessing.)
- [ ] Where did my probability come from, and did it look at the price? (Must be independent.)
- [ ] `edge` run: does `p − a` clear fee + 3 cents on the venue I'd actually trade?
- [ ] Is the same contract cheaper on another venue, after that venue's fees?
- [ ] Spread ≤ 2 cents and displayed depth ≥ my intended size?
- [ ] `size` run: quarter-Kelly stake, then checked against the 5% / 15% / 50% caps?
- [ ] Can I post a resting bid instead of crossing (quarter fee on Kalshi, rebate on Polymarket)?
- [ ] For multi-outcome markets: did I run `arb` on the full set of YES asks first?
- [ ] Days to resolution — is the annualized return worth locking the capital?

## 8. Exits
- **Default: hold to settlement.** The edge thesis is a probability estimate about the
  resolution, so settlement is where it pays. On Kalshi settlement is free; exiting early
  pays a second fee for no reason unless something changed.
- **Exit early when the thesis resolves before the contract does** — the price converges to
  (or past) your estimate, or new information moves your `p` to where the position is no
  longer +EV. Both are the same rule: **re-run `edge` on the current price with your current
  `p`; if it's no longer tradeable in the direction you hold, close.**
- **Exit on a settlement-rule surprise** — the venue clarifies a rule and the contract no
  longer means what you traded. Take the loss immediately; this risk doesn't mean-revert.
- **Never average down on a losing event contract** without a *new* probability estimate from
  a source that isn't the price. A falling price on an event contract is the market telling
  you your `p` was wrong; adding is the classic way a capped-upside instrument produces an
  uncapped-feeling loss.

## 9. Tooling and execution mode
- `research/prediction_market_edge.py` implements the math in §2, §3b, §3d, §5, and §6:
  `fees`, `edge`, `size`, `arb`, `devig`. Stdlib only, no venue API calls — quotes go in on
  the command line, the same split the SPY paper-trade engine uses.
- **There is no MCP tool coverage for event contracts in this repo's Robinhood toolset** —
  the available tools cover equities, options, and crypto only. Prediction-market quotes have
  to be read manually from the venue and passed to the script, so this strategy cannot be
  automated on the SPY playbook's cron pattern until that changes. Screen manually,
  paper-log results, and only then consider automation.
- **Mode: research / paper.** No allocation is assigned in `research/ledger.md` and no real
  order should be placed against this playbook without an explicit instruction to allocate.

## 10. Record keeping
Log every screened trade — including the ones you *skipped* — with: market, settlement source,
your `p`, the ask, the fee-adjusted edge, size, and the outcome. Two reasons this matters more
here than in a technical strategy:
1. **Calibration is the only skill that compounds.** If your 70% estimates resolve YES 55% of
   the time, no fee routing or Kelly fraction saves the strategy — and you can only find that
   out from a log of estimates versus outcomes.
2. **Skipped trades are the control group.** Whether the ones you passed on would have paid is
   the test of whether §5's threshold is set right.

Once an allocation exists, trades settle into `research/ledger.md` under the same rules as
every other strategy: log fills only, recompute the running balance, pause the strategy rather
than force undersized trades.

## Bottom line
Prediction markets are the rare instrument where the edge calculation is exact — EV is just
`p − a − fees` — and that clarity is the trap: it makes it obvious how to compute an edge and
invisible how hard it is to *have* one. The structural work (route to the venue whose fee
shape fits the price, post instead of crossing, size at quarter-Kelly, cap correlated themes)
is worth a few cents per contract and is entirely under your control. The probability estimate
is worth everything else and is not. So spend the effort where §3a points — markets whose
outcome a published model already estimates and few people are watching — and treat every
market where your estimate is really just the price with extra steps as a market to skip.

---
*Fee and venue details verified against public sources, September 2026:*
[Kalshi fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf) ·
[Kalshi help center — fees](https://help.kalshi.com/en/articles/13823805-fees) ·
[Polymarket US fee schedule](https://docs.polymarket.us/fees) ·
[Robinhood event contracts fee summary](https://marketmath.io/platforms/robinhood)
