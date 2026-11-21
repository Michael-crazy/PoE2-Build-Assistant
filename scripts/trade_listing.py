#!/usr/bin/env python3
"""Normalize local market JSON; Tencent support is an offline contract only."""

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path


class ListingError(ValueError):
    """Input cannot be represented without losing listing identity or price."""


def text_field(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ListingError(f"{path}: expected non-empty text")
    return value


def object_field(value, path):
    if not isinstance(value, dict):
        raise ListingError(f"{path}: expected object")
    return value


def normalize_listings(payload, *, league, realm="international"):
    """All-or-nothing conversion; absent prices remain None, never zero.

    League is supplied by the caller and checked against every item's league.
    The complete item is retained for later PoB import; no stat IDs are inferred.
    Realm is caller-supplied provenance, not detected or verified from the input.
    Tencent uses this local contract pending actual samples and supported access.
    """
    text_field(league, "league")
    if realm not in ("international", "tencent"):
        raise ListingError("realm: expected international or tencent")
    payload = object_field(payload, "response")
    if "error" in payload:
        raise ListingError("response contains an upstream error")
    rows = payload.get("result")
    if not isinstance(rows, list):
        raise ListingError("result: expected array")
    output, seen = [], set()
    for index, row in enumerate(rows):
        path = f"result[{index}]"
        row = object_field(row, path)
        identity = text_field(row.get("id"), f"{path}.id")
        if identity in seen:
            raise ListingError(f"{path}.id: duplicate listing {identity}")
        seen.add(identity)
        item = object_field(row.get("item"), f"{path}.item")
        if text_field(item.get("league"), f"{path}.item.league") != league:
            raise ListingError(f"{path}.item.league: does not match requested league")
        text_field(item.get("typeLine"), f"{path}.item.typeLine")
        text_field(item.get("rarity"), f"{path}.item.rarity")
        listing = object_field(row.get("listing"), f"{path}.listing")
        price = listing.get("price")
        if price is not None:
            price = object_field(price, f"{path}.listing.price")
            amount = price.get("amount")
            if (type(amount) not in (int, float) or amount <= 0
                    or (isinstance(amount, float) and not math.isfinite(amount))):
                raise ListingError(f"{path}.listing.price.amount: expected positive finite number")
            price = {
                "amount": amount,
                "currency": text_field(price.get("currency"), f"{path}.listing.price.currency"),
                "type": text_field(price.get("type"), f"{path}.listing.price.type"),
            }
        output.append({"id": identity, "realm": realm, "league": league,
                       "item": deepcopy(item), "price": price})
    return output


def main():
    parser = argparse.ArgumentParser(description="离线读取挂单 JSON；腾讯服仅验证本地契约，未验证真实接口")
    parser.add_argument("input", type=Path)
    parser.add_argument("--league", required=True)
    parser.add_argument("--realm", choices=("international", "tencent"), default="international",
                        help="输入来源，由调用方指定；默认 international")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = normalize_listings(payload, league=args.league, realm=args.realm)
    except (OSError, ValueError) as error:
        parser.exit(1, f"无法读取挂单：{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
