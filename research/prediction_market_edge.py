"""
Trade-screening math for the prediction-market playbook (research/prediction-market-strategy.md).

Binary event contracts settle at $1.00 (YES resolves true) or $0.00 (it doesn't), so a
contract's price is the market's implied probability and every screening question reduces
to arithmetic: is my probability estimate far enough above the ask to survive fees, and
how much size does that edge justify?

This script does no I/O against any venue — quotes are read by hand (or by the agent) and
passed in on the command line, the same split the SPY paper-trade engine uses.

Usage:
    python3 prediction_market_edge.py fees <contracts> <price> [--venue kalshi|robinhood] [--maker]
    python3 prediction_market_edge.py edge <p_est> <ask> [--venue ...] [--contracts N]
    python3 prediction_market_edge.py size <p_est> <ask> <bankroll> [--venue ...] [--kelly 0.25]
    python3 prediction_market_edge.py arb <ask1> <ask2> [ask3 ...] [--venue ...]
    python3 prediction_market_edge.py devig <american_odds1> <american_odds2> [...]

All prices are dollars per contract in [0, 1]. All fee outputs are dollars.
"""
import json
import math
import sys

# Kalshi charges a variance-shaped fee: ceil(multiplier * C * P * (1-P)) to the cent, per
# order (so rounding is amortized over a bigger order, not paid per contract).
KALSHI_TAKER_MULT = 0.07
KALSHI_MAKER_MULT = 0.0175
# Robinhood routes to Kalshi but bills flat: $0.01 commission + $0.01 exchange fee, per
# contract, per side. Price-independent, which is what makes extremes expensive there.
ROBINHOOD_PER_CONTRACT_PER_SIDE = 0.02

VENUES = ("kalshi", "robinhood")


def fee(contracts, price, venue="kalshi", maker=False):
    """Fee in dollars for ONE side (one fill) of `contracts` at `price`."""
    if venue == "robinhood":
        # Flat schedule; maker/taker isn't distinguished.
        return round(ROBINHOOD_PER_CONTRACT_PER_SIDE * contracts, 4)
    mult = KALSHI_MAKER_MULT if maker else KALSHI_TAKER_MULT
    # Round before the ceiling so binary float noise (1.75 -> 1.7500000000000002)
    # can't push the fee a whole cent higher than the schedule says.
    raw = round(mult * contracts * price * (1.0 - price), 6)
    return math.ceil(round(raw * 100.0, 6)) / 100.0


def round_trip_fee(contracts, price, venue="kalshi", maker=False):
    """
    Cost of getting in and back out. Held to settlement, Kalshi charges nothing on the
    settle leg; the conservative assumption for a flat-fee venue is that the closing or
    settling leg bills again, so budget both sides.
    """
    entry = fee(contracts, price, venue, maker)
    if venue == "robinhood":
        return round(entry * 2, 4)
    return entry


def ev_per_contract(p_est, ask, venue="kalshi", contracts=1, maker=False):
    """
    Expected value per contract of buying YES at `ask` when your estimate is `p_est`.

    Gross EV is p*(1-ask) - (1-p)*ask, which collapses to (p - ask): the whole game is
    whether your probability beats the price by more than the fee per contract.
    """
    gross = p_est - ask
    fees = round_trip_fee(contracts, ask, venue, maker) / contracts
    return {
        "gross_edge_per_contract": round(gross, 4),
        "fee_per_contract": round(fees, 4),
        "net_ev_per_contract": round(gross - fees, 4),
        "breakeven_probability": round(ask + fees, 4),
        "tradeable": (gross - fees) > 0,
    }


def required_edge(ask, venue="kalshi", contracts=1, maker=False):
    """Cents of probability edge needed just to break even after fees at this price."""
    return round(round_trip_fee(contracts, ask, venue, maker) / contracts, 4)


def kelly(p_est, ask, bankroll, venue="kalshi", fraction=0.25, contracts_hint=1):
    """
    Kelly for a binary contract bought at `ask`: f* = (p - ask) / (1 - ask), i.e. edge over
    the amount you can lose per dollar of price. Scaled by `fraction` (quarter-Kelly by
    default) because p_est is an estimate, and Kelly on a wrong p is a drawdown machine.
    """
    fees = required_edge(ask, venue, contracts_hint, maker=False)
    net_p = p_est - fees  # fee-adjusted win probability, so sizing can't ignore costs
    if ask <= 0 or ask >= 1:
        return {"error": "ask must be strictly between 0 and 1"}
    full = (net_p - ask) / (1.0 - ask)
    scaled = max(0.0, full * fraction)
    stake = bankroll * scaled
    return {
        "full_kelly_fraction": round(full, 4),
        "scaled_kelly_fraction": round(scaled, 4),
        "stake_dollars": round(stake, 2),
        "contracts": int(stake // ask) if ask > 0 else 0,
        "max_loss_dollars": round(int(stake // ask) * ask, 2),
    }


def dutch_book(asks, venue="kalshi"):
    """
    Mutually exclusive outcomes must sum to $1.00. If every YES ask sums to less than
    $1.00 net of fees, buying one of each locks a profit regardless of which resolves.

    Fees are charged at the 1-contract-per-leg rate, which pays the per-order cent rounding
    on every leg — the worst case. Buying the set in size amortizes that rounding, so a set
    that clears here also clears at larger size.
    """
    total = sum(asks)
    fees = sum(required_edge(a, venue) for a in asks)
    net_cost = total + fees
    return {
        "outcomes": len(asks),
        "sum_of_asks": round(total, 4),
        "total_fees_per_set": round(fees, 4),
        "net_cost_per_set": round(net_cost, 4),
        "payout_per_set": 1.0,
        "profit_per_set": round(1.0 - net_cost, 4),
        "arb": net_cost < 1.0,
    }


def american_to_implied(odds):
    """Sportsbook American odds -> implied probability, vig included."""
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def devig(odds_list):
    """
    Strip the book's vig by normalizing implied probabilities to sum to 1. The result is a
    fair-odds probability you can price a prediction-market contract against.
    """
    raw = [american_to_implied(o) for o in odds_list]
    overround = sum(raw)
    return {
        "raw_implied": [round(r, 4) for r in raw],
        "overround": round(overround, 4),
        "vig_pct": round((overround - 1.0) * 100, 2),
        "fair_probabilities": [round(r / overround, 4) for r in raw],
    }


def _flag(args, name, default=None, cast=str):
    if name in args:
        return cast(args[args.index(name) + 1])
    return default


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd, args = argv[1], argv[2:]
    venue = _flag(args, "--venue", "kalshi")
    if venue not in VENUES:
        print(json.dumps({"error": f"venue must be one of {VENUES}"}))
        return 1
    maker = "--maker" in args
    pos = [a for a in args if not a.startswith("--")]
    # Drop values consumed by flags that take one.
    for f in ("--venue", "--contracts", "--kelly"):
        if f in args:
            val = args[args.index(f) + 1]
            if val in pos:
                pos.remove(val)

    if cmd == "fees":
        contracts, price = int(pos[0]), float(pos[1])
        out = {
            "venue": venue,
            "contracts": contracts,
            "price": price,
            "one_side_fee": fee(contracts, price, venue, maker),
            "round_trip_fee": round_trip_fee(contracts, price, venue, maker),
            "per_contract_round_trip": required_edge(price, venue, contracts, maker),
        }
    elif cmd == "edge":
        p_est, ask = float(pos[0]), float(pos[1])
        contracts = _flag(args, "--contracts", 1, int)
        out = ev_per_contract(p_est, ask, venue, contracts, maker)
        out["venue"] = venue
    elif cmd == "size":
        p_est, ask, bankroll = float(pos[0]), float(pos[1]), float(pos[2])
        out = kelly(p_est, ask, bankroll, venue, _flag(args, "--kelly", 0.25, float))
        out["venue"] = venue
    elif cmd == "arb":
        out = dutch_book([float(a) for a in pos], venue)
        out["venue"] = venue
    elif cmd == "devig":
        out = devig([float(a) for a in pos])
    else:
        print(__doc__)
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
