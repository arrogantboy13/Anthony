"""
Fair-value screen for Kalshi's 15-minute BTC up/down contracts (KXBTC15M).

The contract asks: is the 60-second average of CF Benchmarks' BRTI before the close at
least the 60-second average before the open? Over 15 minutes BTC drift is negligible next
to its volatility, so the fair probability is just how far spot sits from the target,
measured in standard deviations of the remaining time:

    fair = Phi( (spot - target) / (sigma_1min * sqrt(T_eff) * spot) )

where T_eff = minutes remaining - 0.5, because settlement is a 60-second AVERAGE ending at
the close, not a spot print at the close — the observation is effectively centered half a
minute early, and part of it is already locked in as the window ends.

This does NOT tell you which way BTC will go. It tells you what the price should be given
where BTC already is, so you can see whether a quote is off-model by more than it costs to
trade. Empirically (see research/btc-15min-strategy.md) it usually isn't.

Run it on demand; it fetches nothing on a schedule and places no orders.

Usage:
    python3 btc15m_fair_value.py                      # live: current window vs live spot
    python3 btc15m_fair_value.py --vol-bars 120       # longer realized-vol lookback
    python3 btc15m_fair_value.py --offline <spot> <target> <mins_left> <ask> [<bid>]
"""
import json
import math
import sys
import urllib.request

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
COINBASE = "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60"
COINBASE_TICKER = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
EDGE_BUFFER = 0.03  # model-error haircut, same as the playbook's entry threshold


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "research-script"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def kalshi_fee(price, contracts=1):
    """Taker fee, ceil-to-cent per ORDER — so it amortizes over a larger order."""
    raw = round(0.07 * contracts * price * (1.0 - price), 6)
    return math.ceil(round(raw * 100.0, 6)) / 100.0


def realized_sigma_1min(bars=350):
    """
    Per-minute log-return stdev from recent 1-minute BTC candles, plus a LIVE spot.

    Spot comes from the ticker endpoint, never from the last candle's close. The last
    1-minute candle can be several minutes stale, and over a 15-minute window one standard
    deviation is only ~$75 on an $80k coin — so a $35 stale-price error is half a standard
    deviation, which shows up as ~17 points of phantom "edge" against a market that is
    actually priced correctly. Feed latency is the binding constraint on this strategy,
    not the model.
    """
    c = sorted(_get(COINBASE), key=lambda r: r[0])[-bars:]
    closes = [r[4] for r in c]
    rets = [math.log(closes[i + 1] / closes[i]) for i in range(len(closes) - 1)]
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / n
    spot = float(_get(COINBASE_TICKER)["price"])
    return math.sqrt(var), spot, n


def fair_probability(spot, target, mins_left, sigma_1min):
    """Phi(d) with the 60-second-average adjustment described above."""
    t_eff = max(mins_left - 0.5, 0.05)
    denom = sigma_1min * math.sqrt(t_eff) * spot
    if denom <= 0:
        return 1.0 if spot >= target else 0.0
    return norm_cdf((spot - target) / denom)


def screen(spot, target, mins_left, sigma_1min, ask, bid, contracts=1):
    fair = fair_probability(spot, target, mins_left, sigma_1min)
    spread = (ask - bid) if (ask is not None and bid is not None) else 0.0
    out = {"spot": round(spot, 2), "target": round(target, 2),
           "distance_dollars": round(spot - target, 2),
           "mins_left": round(mins_left, 2),
           "sigma_1min_pct": round(sigma_1min * 100, 4),
           "one_sd_move_dollars": round(sigma_1min * math.sqrt(max(mins_left - 0.5, 0.05)) * spot, 0),
           "dollars_per_probability_point": round(
               sigma_1min * math.sqrt(max(mins_left - 0.5, 0.05)) * spot / 39.9, 1),
           "fair_yes": round(fair, 4), "yes_bid": bid, "yes_ask": ask,
           "spread": round(spread, 4)}
    for side, price, p_win in (("YES", ask, fair), ("NO", (1 - bid) if bid is not None else None, 1 - fair)):
        if price is None:
            continue
        fee = kalshi_fee(price, contracts) / contracts
        hurdle = fee + spread / 2.0
        edge = p_win - price - fee
        out[f"buy_{side.lower()}"] = {
            "price": round(price, 4), "fee_per_contract": round(fee, 4),
            "hurdle_per_contract": round(hurdle, 4),
            "net_edge": round(edge, 4),
            "tradeable": edge >= EDGE_BUFFER,
        }
    return out


def live(vol_bars=350):
    ms = _get(f"{KALSHI}/markets?limit=20&status=open&series_ticker=KXBTC15M").get("markets", [])
    if not ms:
        return {"error": "no open KXBTC15M market right now"}
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    sigma, spot, nbars = realized_sigma_1min(vol_bars)
    results = []
    for m in ms:
        sub = m.get("yes_sub_title") or ""
        try:
            target = float(sub.split("$")[1].replace(",", ""))
        except (IndexError, ValueError):
            continue
        close = dt.datetime.strptime(m["close_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        mins_left = (close - now).total_seconds() / 60.0
        if mins_left <= 0:
            continue
        ask = float(m["yes_ask_dollars"]) if m.get("yes_ask_dollars") else None
        bid = float(m["yes_bid_dollars"]) if m.get("yes_bid_dollars") else None
        r = screen(spot, target, mins_left, sigma, ask, bid)
        r["ticker"] = m["ticker"]
        r["vol_bars_used"] = nbars
        results.append(r)
    return results


def main(argv):
    if "--offline" in argv:
        i = argv.index("--offline")
        a = argv[i + 1:]
        spot, target, mins, ask = float(a[0]), float(a[1]), float(a[2]), float(a[3])
        bid = float(a[4]) if len(a) > 4 else ask
        sigma = 0.000292  # fallback: recent BTC 1-min realized vol
        print(json.dumps(screen(spot, target, mins, sigma, ask, bid), indent=2))
        return 0
    bars = 350
    if "--vol-bars" in argv:
        bars = int(argv[argv.index("--vol-bars") + 1])
    print(json.dumps(live(bars), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
