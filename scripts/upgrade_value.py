#!/usr/bin/env python3
"""Offline value calculation over normalized listings and completed PoB trials."""

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path

from pob_trial import METRICS
from trade_listing import object_field, text_field


def number(value, path, *, positive=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or (value <= 0 if positive else value < 0)):
        raise ValueError(f"{path}: expected {'positive' if positive else 'non-negative'} finite number")
    return value


def calculate_upgrade(listing, trial, *, realm, league, currency, metric, rates=None):
    """Return metric units gained per currency unit; rates are base units per unit.

    Caller associates a completed trial with its normalized listing. No equipment
    import, trial execution, live pricing, or inferred survival score occurs here.
    """
    if realm not in ("international", "tencent"):
        raise ValueError("realm: expected international or tencent")
    text_field(league, "league")
    text_field(currency, "currency")
    if metric not in METRICS:
        raise ValueError("metric: expected one of " + ", ".join(METRICS))
    listing = object_field(listing, "listing")
    text_field(listing.get("id"), "listing.id")
    if listing.get("realm") != realm or listing.get("league") != league:
        raise ValueError("listing realm/league does not match requested context")
    trial = object_field(trial, "trial")
    delta = {}
    for key in METRICS:
        before = number(object_field(trial.get("baseline"), "baseline").get(key), f"baseline.{key}")
        after = number(object_field(trial.get("replacement"), "replacement").get(key), f"replacement.{key}")
        delta[key] = after - before
    result = {"id": listing["id"], "realm": realm, "league": league,
              "price": deepcopy(listing.get("price")), "trial": deepcopy(trial),
              "delta": delta, "metric": metric, "currency": currency,
              "normalized_price": None, "gain_per_currency": None, "rate_used": None,
              "gain_percent": None, "gain_percent_per_currency": None}
    baseline = trial["baseline"][metric]
    if baseline > 0:
        percent = delta[metric] / baseline * 100
        if math.isfinite(percent):
            result["gain_percent"] = percent
    price = listing.get("price")
    if price is None:
        return {**result, "status": "missing_price"}
    price = object_field(price, "price")
    amount = number(price.get("amount"), "price.amount", positive=True)
    source_currency = text_field(price.get("currency"), "price.currency")
    rate = 1
    if source_currency != currency:
        if rates is None:
            return {**result, "status": "missing_rate"}
        rates = object_field(rates, "rates")
        if rates.get("realm") != realm or rates.get("league") != league:
            return {**result, "status": "rate_context_mismatch"}
        if rates.get("currency") != currency:
            return {**result, "status": "rate_currency_mismatch"}
        values = object_field(rates.get("units"), "rates.units")
        if source_currency not in values:
            return {**result, "status": "missing_rate"}
        rate = number(values[source_currency], f"rates.units.{source_currency}", positive=True)
    normalized = amount * rate
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("normalized price is outside finite positive range")
    value = delta[metric] / normalized
    if not math.isfinite(value):
        raise ValueError("gain per currency is outside finite range")
    if result["gain_percent"] is not None:
        percent_value = result["gain_percent"] / normalized
        if math.isfinite(percent_value):
            result["gain_percent_per_currency"] = percent_value
    return {**result, "status": "ok", "normalized_price": normalized,
            "gain_per_currency": value, "rate_used": rate}


def add_value_arguments(parser):
    parser.add_argument("input", type=Path, help="包含挂单、试穿结果和可选汇率的 JSON 文件")


def run_value_command(parser, args):
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        context = object_field(payload["context"], "context")
        output = [calculate_upgrade(row["listing"], row["trial"], **context,
                                    rates=payload.get("rates")) for row in payload["candidates"]]
        print(json.dumps(output, ensure_ascii=False, allow_nan=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        parser.exit(1, f"性价比计算失败：{error}\n")
    return 0


def main():
    parser = argparse.ArgumentParser(description="计算换装性价比")
    add_value_arguments(parser)
    return run_value_command(parser, parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
