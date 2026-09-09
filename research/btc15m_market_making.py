"""
Market-making estimate for KXBTC15M, with adverse-selection bounds.

Taking liquidity on these markets is a measured loser, so this asks the other question:
what does POSTING liquidity earn? Two reasons to treat it separately:

  * It is drift-neutral by construction. Quote both sides and you capture the spread with no
    directional exposure, which sidesteps the sample-drift confound that produced every fake
    edge in btc-15min-strategy.md.
  * The maker fee is roughly a quarter of the taker fee, and the fee is most of the cost.

The honest catch is adverse selection: you get filled precisely when the market is moving
against you. That cannot be measured exactly from public data — there is no fill feed — so
this reports a RANGE, using the minute-by-minute direction of the mid as a proxy for which
side informed flow hit. Treat the optimistic bound as fiction and the realistic one as the
planning number.

Fees are un-rounded (multiplier x p x (1-p)) because a real maker quotes size, so the
per-order cent rounding amortizes away.

Usage:
    python3 btc15m_market_making.py [--cache-dir DIR] [--limit 200]
"""
import glob
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

API = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXBTC15M"
TAKER_THETA, MAKER_THETA = 0.07, 0.0175
# Polymarket US publishes the same formula shape with a maker REBATE instead of a fee.
PM_TAKER_THETA, PM_MAKER_THETA = 0.06, -0.0125


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "research-script"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fee(price, theta):
    return theta * price * (1.0 - price)


def load(cache, limit):
    os.makedirs(cache, exist_ok=True)
    meta = {}
    for m in _get(f"{API}/markets?limit={limit}&status=settled&series_ticker={SERIES}")["markets"]:
        close = int(datetime.strptime(m["close_time"], "%Y-%m-%dT%H:%M:%SZ")
                    .replace(tzinfo=timezone.utc).timestamp())
        meta[m["ticker"]] = (1 if m["result"] == "yes" else 0, close)
    obs = []
    for ticker, (out, close) in meta.items():
        path = os.path.join(cache, ticker + ".json")
        if not os.path.exists(path):
            url = (f"{API}/series/{SERIES}/markets/{ticker}/candlesticks"
                   f"?start_ts={close - 900}&end_ts={close + 60}&period_interval=1")
            try:
                with open(path, "w") as f:
                    json.dump(_get(url), f)
            except Exception as e:
                print(f"  warn: {ticker}: {e}", file=sys.stderr)
                continue
        pts = []
        for c in json.load(open(path)).get("candlesticks", []):
            a = c.get("yes_ask", {}).get("close_dollars")
            b = c.get("yes_bid", {}).get("close_dollars")
            if not a or not b:
                continue
            a, b = float(a), float(b)
            if not (0 < a <= 1 and 0 <= b <= 1 and b <= a):
                continue
            pts.append(((close - c["end_period_ts"]) / 60.0, a, b, (a + b) / 2))
        pts.sort(key=lambda x: -x[0])
        for i in range(len(pts) - 1):
            mins_left, a, b, mid = pts[i]
            if 2 <= mins_left <= 15:
                obs.append({"a": a, "b": b, "mid": mid, "out": out, "nxt": pts[i + 1][3]})
    return obs


def main(argv):
    cache = argv[argv.index("--cache-dir") + 1] if "--cache-dir" in argv else ".kxbtc15m_cache"
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 200
    obs = load(cache, limit)
    n = len(obs)
    if not n:
        print("no observations")
        return 1
    spread = sum(o["a"] - o["b"] for o in obs) / n
    print(f"observations: {n}   average spread: {spread:.4f}")

    print("\n--- 1. does the spread cover the maker fee? ---")
    mf = sum(fee(o["mid"], MAKER_THETA) for o in obs) / n
    tf = sum(fee(o["mid"], TAKER_THETA) for o in obs) / n
    print(f"capture per round turn (buy bid, sell ask): {spread:+.4f}")
    print(f"two maker fees, one per side              : {-2*mf:+.4f}")
    print(f"NET before adverse selection              : {spread-2*mf:+.4f}   <- pure spread capture")
    print(f"  (the same round turn paying TAKER fees  : {spread-2*tf:+.4f})")

    print("\n--- 2. adverse selection: what happens right after a fill? ---")
    hit = [o for o in obs if o["nxt"] < o["mid"]]     # mid ticks down -> you were hit on the bid
    lift = [o for o in obs if o["nxt"] > o["mid"]]    # mid ticks up   -> you were lifted on the ask
    flat = [o for o in obs if o["nxt"] == o["mid"]]

    def ev_bid(g):
        return sum(o["out"] - o["b"] - fee(o["b"], MAKER_THETA) for o in g) / len(g)

    def ev_ask(g):
        return sum((1 - o["out"]) - (1 - o["a"]) - fee(1 - o["a"], MAKER_THETA) for o in g) / len(g)

    print(f"mid fell (hit on your bid)   : {len(hit):5d}  ({100*len(hit)/n:.0f}%)")
    print(f"mid rose (lifted on your ask): {len(lift):5d}  ({100*len(lift)/n:.0f}%)")
    print(f"mid flat (the benign fills)  : {len(flat):5d}  ({100*len(flat)/n:.0f}%)")
    print(f"\nEV of a BID fill  | all fills {ev_bid(obs):+.4f} | only when mid fell {ev_bid(hit):+.4f}")
    print(f"EV of an ASK fill | all fills {ev_ask(obs):+.4f} | only when mid rose {ev_ask(lift):+.4f}")
    adverse = ((ev_bid(hit) - ev_bid(obs)) + (ev_ask(lift) - ev_ask(obs))) / 2
    print(f"\nadverse-selection cost per fill: {adverse:+.4f}")

    print("\n--- 3. the range, per venue fee schedule ---")
    print(f"{'venue':<16}{'base':>10}{'realistic':>12}{'pessimistic':>13}{'breakeven needs adv <':>23}")
    for label, theta in (("Kalshi", MAKER_THETA), ("Polymarket US", PM_MAKER_THETA)):
        mfee = sum(fee(o["mid"], theta) for o in obs) / n
        base = spread - 2 * mfee
        print(f"{label:<16}{base:>+10.4f}{base+adverse/2:>+12.4f}{base+adverse:>+13.4f}{base:>23.4f}")
    print(f"\nmeasured adverse selection here: {abs(adverse):.4f}/fill — so a rebate venue needs a")
    print("market with materially less informed flow than a 15-minute BTC coin flip.")
    print("\nNot modelled: queue position, inventory risk, or the chance your quote simply")
    print("never fills. All three make the real number worse than the range above.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
