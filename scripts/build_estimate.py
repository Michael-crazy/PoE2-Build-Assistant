#!/usr/bin/env python3
"""Aggregate supplied slot quotes offline, without matching or market queries."""

import argparse
from copy import deepcopy
from decimal import Decimal
import json
import math
from pathlib import Path

from trade_listing import object_field, text_field
from upgrade_value import number


def aggregate_quotes(slots, *, realm, league):
    """One caller-selected normalized listing per slot; no currency conversion.

    Caller supplies the complete intended slot inventory and matched affixes.
    Missing rows cannot be inferred from a BD here. A subtotal is never a full
    build price, even if every supplied slot has a quote.
    """
    if realm not in ("international", "tencent"):
        raise ValueError("realm: expected international or tencent")
    text_field(league, "league")
    if not isinstance(slots, list) or not slots:
        raise ValueError("slots: expected non-empty array")
    rows, matched, missing, seen, totals = [], [], [], set(), {}
    for index, supplied in enumerate(slots):
        path = f"slots[{index}]"
        supplied = object_field(supplied, path)
        slot = text_field(supplied.get("slot"), f"{path}.slot")
        if slot in seen:
            raise ValueError(f"{path}.slot: duplicate slot {slot}")
        seen.add(slot)
        affixes = supplied.get("matched_affixes")
        if not isinstance(affixes, list):
            raise ValueError(f"{path}.matched_affixes: expected array")
        for affix in affixes:
            text_field(affix, f"{path}.matched_affixes[]")
        if "listing" not in supplied:
            raise ValueError(f"{path}.listing: required (null for no match)")
        listing = supplied["listing"]
        status = "missing_listing"
        if listing is None:
            if affixes:
                raise ValueError(f"{path}: matched affixes require a listing")
        else:
            listing = object_field(listing, f"{path}.listing")
            text_field(listing.get("id"), f"{path}.listing.id")
            if listing.get("realm") != realm or listing.get("league") != league:
                raise ValueError(f"{path}.listing: realm/league does not match requested context")
            object_field(listing.get("item"), f"{path}.listing.item")
            if "price" not in listing:
                raise ValueError(f"{path}.listing.price: required (null for unpriced)")
            matched.append(slot)
            status = "missing_price"
            if listing["price"] is not None:
                price = object_field(listing["price"], f"{path}.listing.price")
                amount = number(price.get("amount"), f"{path}.listing.price.amount", positive=True)
                currency = text_field(price.get("currency"), f"{path}.listing.price.currency")
                totals[currency] = totals.get(currency, Decimal(0)) + Decimal(str(amount))
                status = "quoted"
        if "build_item" in supplied and supplied["build_item"] is None:
            if listing is not None or affixes:
                raise ValueError(f"{path}: empty build slot cannot select a listing")
            status = "empty_slot"
        if status not in ("quoted", "empty_slot"):
            missing.append({"slot": slot, "reason": status})
        rows.append({"slot": slot, "matched_affixes": deepcopy(affixes),
                     "listing": deepcopy(listing), "status": status})
        if "build_item" in supplied:
            rows[-1]["build_item"] = deepcopy(supplied["build_item"])
    subtotals = {currency: float(amount) for currency, amount in totals.items()}
    if any(not math.isfinite(amount) for amount in subtotals.values()):
        raise ValueError("subtotal is outside finite range")
    return {"realm": realm, "league": league, "slots": rows,
            "matched_slots": matched, "missing_slots": missing,
            "quoted_slot_count": sum(row["status"] == "quoted" for row in rows),
            "subtotals_by_currency": subtotals}


def estimate_file(path: Path):
    """Read one offline quote snapshot using the shared aggregation contract."""
    payload = object_field(json.loads(path.read_text(encoding="utf-8")), "input")
    context = object_field(payload.get("context"), "context")
    return aggregate_quotes(payload.get("slots"), **context)


def main():
    parser = argparse.ArgumentParser(description="离线汇总逐槽参考报价；不查询市场或换汇")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        result = estimate_file(args.input)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    except (OSError, ValueError, TypeError, OverflowError) as error:
        parser.exit(1, f"整套估价汇总失败：{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
