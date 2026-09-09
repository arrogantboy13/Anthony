"""
Measures the fair-value model in research/btc15m_fair_value.py against the market.

Produces the two constants that script uses to gate its signals (MODEL_BIAS, RESIDUAL_SD)
and — more importantly — answers whether the model is actually more accurate than the
market. It is not, and the gate depends on that being honest.

Method: replay every settled KXBTC15M window minute by minute, reconstruct what the model
would have said from the BTC spot and trailing realized vol available at that moment, and
compare to the market's mid at the same moment and to what actually happened.

Three outputs:
  1. bias    — mean(model fair - market mid). The model's standing offset.
  2. noise   — stdev of that difference. How far the model routinely lands from the market.
  3. skill   — Brier scores for model vs market, with a bootstrap CI clustered BY WINDOW.
               Clustering matters: 15 observations from one window are one price path, so
               the effective sample is ~200, not ~2,600. Without clustering the model looks
               significantly better than the market; with it, the CI includes zero.

Public APIs only, no auth, nothing scheduled.

Usage:
    python3 btc15m_model_calibration.py [--limit 200] [--cache-dir DIR]
"""
import bisect
import json
import math
import os
import random
import statistics
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

API = "https://api.elections.kalshi.com/trade-api/v2"
CB = "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60"
SERIES = "KXBTC15M"
VOL_LOOKBACK = 350


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "research-script"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_spot(start, end):
    """1-minute BTC closes over [start, end]; Coinbase caps a request at ~300 candles."""
    out, cur = {}, start
    while cur < end:
        nxt = min(cur + timedelta(minutes=295), end)
        url = (f"{CB}&start={cur.isoformat().replace('+00:00', 'Z')}"
               f"&end={nxt.isoformat().replace('+00:00', 'Z')}")
        try:
            for row in _get(url):
                out[row[0]] = row[4]
        except Exception as e:
            print(f"  warn: spot fetch {cur}: {e}", file=sys.stderr)
        cur = nxt
    return out


def main(argv):
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 200
    cache = argv[argv.index("--cache-dir") + 1] if "--cache-dir" in argv else ".kxbtc15m_cache"
    os.makedirs(cache, exist_ok=True)

    markets = _get(f"{API}/markets?limit={limit}&status=settled&series_ticker={SERIES}")["markets"]
    meta = {}
    for m in markets:
        try:
            target = float(m["yes_sub_title"].split("$")[1].replace(",", ""))
        except (KeyError, IndexError, ValueError, AttributeError):
            continue
        close = int(datetime.strptime(m["close_time"], "%Y-%m-%dT%H:%M:%SZ")
                    .replace(tzinfo=timezone.utc).timestamp())
        meta[m["ticker"]] = (1 if m["result"] == "yes" else 0, close, target, m["close_time"][:10])
    if not meta:
        print("no settled markets with a parseable target")
        return 1

    lo = datetime.fromtimestamp(min(v[1] for v in meta.values()), timezone.utc) - timedelta(minutes=VOL_LOOKBACK + 30)
    hi = datetime.fromtimestamp(max(v[1] for v in meta.values()), timezone.utc) + timedelta(minutes=5)
    print(f"replaying {len(meta)} windows; fetching spot {lo:%Y-%m-%d %H:%M} -> {hi:%Y-%m-%d %H:%M}Z")
    spot = fetch_spot(lo, hi)
    keys = sorted(spot)
    print(f"spot minutes: {len(keys)}")

    def spot_at(ts):
        i = bisect.bisect_right(keys, ts)
        return spot[keys[i - 1]] if i > 0 else None

    def sigma_at(ts):
        i = bisect.bisect_right(keys, ts)
        xs = [spot[k] for k in keys[max(0, i - VOL_LOOKBACK - 1):i]]
        if len(xs) < 30:
            return None
        rets = [math.log(xs[j + 1] / xs[j]) for j in range(len(xs) - 1)]
        return statistics.pstdev(rets)

    per_window = defaultdict(list)
    for ticker, (out, close, target, day) in meta.items():
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
        for c in json.load(open(path)).get("candlesticks", []):
            a = c.get("yes_ask", {}).get("close_dollars")
            b = c.get("yes_bid", {}).get("close_dollars")
            if not a or not b:
                continue
            a, b = float(a), float(b)
            if not (0 < a <= 1 and 0 <= b <= 1 and b <= a):
                continue
            ts = c["end_period_ts"]
            mins_left = (close - ts) / 60.0
            if not (2 <= mins_left <= 15):     # the final minutes are pinned; they tell us nothing
                continue
            s, sg = spot_at(ts), sigma_at(ts)
            if not s or not sg:
                continue
            t_eff = max(mins_left - 0.5, 0.05)
            d = (s - target) / (sg * math.sqrt(t_eff) * s)
            fair = 0.5 * (1 + math.erf(d / math.sqrt(2)))
            per_window[ticker].append({"fair": fair, "mid": (a + b) / 2, "out": out, "day": day})

    flat = [x for w in per_window.values() for x in w]
    n = len(flat)
    resid = [x["fair"] - x["mid"] for x in flat]
    print(f"\npaired observations: {n} across {len(per_window)} windows")
    print("\n--- 1. bias and noise (these are the script's constants) ---")
    print(f"MODEL_BIAS  = {statistics.mean(resid):+.4f}   mean(fair - market mid)")
    print(f"RESIDUAL_SD =  {statistics.pstdev(resid):.4f}   stdev of that disagreement")

    print("\n--- 2. skill: is the model actually better than the market? ---")
    bm = sum((x["mid"] - x["out"]) ** 2 for x in flat) / n
    bf = sum((x["fair"] - x["out"]) ** 2 for x in flat) / n
    print(f"Brier market: {bm:.4f}    Brier model: {bf:.4f}    (always-50/50: 0.2500)")

    print("\n--- 3. drift control: same comparison, split by day ---")
    print(f"{'day':<12}{'windows':>9}{'base YES%':>11}{'Brier mkt':>11}{'Brier model':>12}{'winner':>9}")
    byday = defaultdict(list)
    for w in per_window.values():
        byday[w[0]["day"]].append(w)
    for day in sorted(byday):
        ws = byday[day]
        f2 = [x for w in ws for x in w]
        dm = sum((x["mid"] - x["out"]) ** 2 for x in f2) / len(f2)
        df = sum((x["fair"] - x["out"]) ** 2 for x in f2) / len(f2)
        base = sum(w[0]["out"] for w in ws) / len(ws)
        print(f"{day:<12}{len(ws):>9}{100*base:>10.1f}%{dm:>11.4f}{df:>12.4f}"
              f"{('model' if df < dm else 'MARKET'):>9}")

    print("\n--- 4. significance, resampling WINDOWS (not observations) ---")
    wins = list(per_window.values())

    def advantage(sample):
        f2 = [x for w in sample for x in w]
        return (sum((x["mid"] - x["out"]) ** 2 for x in f2)
                - sum((x["fair"] - x["out"]) ** 2 for x in f2)) / len(f2)

    random.seed(0)
    boot = sorted(advantage([random.choice(wins) for _ in wins]) for _ in range(2000))
    lo_ci, hi_ci = boot[50], boot[1949]
    print(f"Brier advantage (market - model): {advantage(wins):+.4f}")
    print(f"95% bootstrap CI over {len(wins)} windows: [{lo_ci:+.4f}, {hi_ci:+.4f}]")
    if lo_ci > 0:
        print("=> CI excludes zero: the model genuinely beats the market on this sample.")
    else:
        print("=> CI INCLUDES ZERO: the model is NOT more accurate than the market.")
        print("   So a model/market disagreement is not evidence the market is wrong, and")
        print("   btc15m_fair_value.py must not emit a signal on disagreement alone.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
