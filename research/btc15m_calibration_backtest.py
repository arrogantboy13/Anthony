"""
Calibration backtest for Kalshi's 15-minute BTC up/down markets (KXBTC15M).

Reproduces every number in research/btc-15min-strategy.md. Pulls settled windows and their
per-minute price history from Kalshi's public API (no auth, no orders, nothing scheduled),
then answers one question: is there a pricing error big enough to trade?

The headline test is the two-sided one. In a calibrated market the EV of buying YES and the
EV of buying NO must sum to exactly the cost of trading — whatever one side wins the other
loses, minus the house's take. If the sum is meaningfully better than -(spread + both fees),
somebody is leaving money on the table. If it isn't, nobody is.

It also runs the drift control, because the naive per-bucket result on this market says
"always buy NO" and that is an artifact of which way BTC happened to move in the sample.

Usage:
    python3 btc15m_calibration_backtest.py [--limit 200] [--cache-dir DIR]
"""
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

API = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXBTC15M"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "research-script"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def kalshi_fee(price, contracts=1):
    raw = round(0.07 * contracts * price * (1.0 - price), 6)
    return math.ceil(round(raw * 100.0, 6)) / 100.0


def load(limit, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    settled = _get(f"{API}/markets?limit={limit}&status=settled&series_ticker={SERIES}")["markets"]
    obs = []
    outcomes = {}
    for m in settled:
        close = int(datetime.strptime(m["close_time"], "%Y-%m-%dT%H:%M:%SZ")
                    .replace(tzinfo=timezone.utc).timestamp())
        out = 1 if m["result"] == "yes" else 0
        outcomes[m["ticker"]] = (out, m["close_time"][:10])
        path = os.path.join(cache_dir, m["ticker"] + ".json")
        if not os.path.exists(path):
            url = (f"{API}/series/{SERIES}/markets/{m['ticker']}/candlesticks"
                   f"?start_ts={close - 900}&end_ts={close + 60}&period_interval=1")
            try:
                with open(path, "w") as f:
                    json.dump(_get(url), f)
            except Exception as e:            # a single bad window shouldn't kill the run
                print(f"  warn: {m['ticker']}: {e}", file=sys.stderr)
                continue
        for c in json.load(open(path)).get("candlesticks", []):
            a = c.get("yes_ask", {}).get("close_dollars")
            b = c.get("yes_bid", {}).get("close_dollars")
            if not a or not b:
                continue
            a, b = float(a), float(b)
            if not (0 < a <= 1 and 0 <= b <= 1 and b <= a):
                continue
            mins_left = (close - c["end_period_ts"]) / 60.0
            if 0 <= mins_left <= 15:
                obs.append({"day": m["close_time"][:10], "mins_left": mins_left,
                            "bid": b, "ask": a, "mid": (a + b) / 2, "out": out})
    return settled, outcomes, obs


def main(argv):
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 200
    cache = argv[argv.index("--cache-dir") + 1] if "--cache-dir" in argv else ".kxbtc15m_cache"
    settled, outcomes, obs = load(limit, cache)
    n = len(obs)
    wins = sum(o for o, _ in outcomes.values())
    print(f"windows: {len(outcomes)}   observations: {n}")
    print(f"base rate YES: {100*wins/len(outcomes):.1f}%  ({wins}/{len(outcomes)})")

    ev_yes = sum(o["out"] - o["ask"] - kalshi_fee(o["ask"]) for o in obs) / n
    ev_no = sum((1 - o["out"]) - (1 - o["bid"]) - kalshi_fee(1 - o["bid"]) for o in obs) / n
    spread = sum(o["ask"] - o["bid"] for o in obs) / n
    fee = sum(kalshi_fee(o["mid"]) for o in obs) / n
    structural = -(spread + 2 * fee)
    print("\n--- two-sided calibration test ---")
    print(f"EV buy YES: {ev_yes:+.4f}/ct    EV buy NO: {ev_no:+.4f}/ct    sum: {ev_yes+ev_no:+.4f}")
    print(f"structural cost -(spread + 2 fees): {structural:+.4f}")
    print(f"gap (mispricing available):         {(ev_yes+ev_no)-structural:+.4f}")

    print("\n--- drift control: does the NO 'edge' just track that day's BTC direction? ---")
    print(f"{'day':<12}{'windows':>9}{'base YES%':>11}{'EV buy NO':>12}")
    byday = defaultdict(list)
    wday = defaultdict(list)
    for o in obs:
        byday[o["day"]].append(o)
    for out, day in outcomes.values():
        wday[day].append(out)
    for day in sorted(byday):
        g, w = byday[day], wday[day]
        noev = sum((1 - x["out"]) - (1 - x["bid"]) - kalshi_fee(1 - x["bid"]) for x in g) / len(g)
        print(f"{day:<12}{len(w):>9}{100*sum(w)/len(w):>10.1f}%{noev:>12.4f}")

    print("\n--- cost to take liquidity, by price (half-spread + fee) ---")
    print(f"{'mid bucket':<13}{'n':>6}{'spread':>9}{'fee':>8}{'hurdle/ct':>11}")
    b = defaultdict(list)
    for o in obs:
        b[min(int(o["mid"] * 10) / 10, 0.9)].append(o)
    for lo in sorted(b):
        g = b[lo]
        sp = sum(x["ask"] - x["bid"] for x in g) / len(g)
        f = sum(kalshi_fee(x["mid"]) for x in g) / len(g)
        print(f"{f'{lo:.1f}-{lo+0.1:.1f}':<13}{len(g):>6}{sp:>9.4f}{f:>8.4f}{sp/2+f:>11.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
