"""Assemble explicit offline slot selections into the M04 quote contract."""

from copy import deepcopy
import json
from pathlib import Path

from build_slots import bind_selections, engine_build, extract_build
from build_estimate import aggregate_quotes
from trade_listing import normalize_listings, object_field, text_field


def assemble_quotes(listings, selections, *, realm, league):
    """Select normalized references by ID; never infer slots or affix matches."""
    if not isinstance(listings, list):
        raise ValueError("listings: expected array")
    by_id = {}
    for index, listing in enumerate(listings):
        path = f"listings[{index}]"
        listing = object_field(listing, path)
        identity = text_field(listing.get("id"), f"{path}.id")
        if identity in by_id:
            raise ValueError(f"{path}.id: duplicate listing {identity}")
        if listing.get("realm") != realm or listing.get("league") != league:
            raise ValueError(f"{path}: realm/league does not match requested context")
        by_id[identity] = listing
    if not isinstance(selections, list):
        raise ValueError("selections: expected array")
    slots = []
    for index, selection in enumerate(selections):
        path = f"selections[{index}]"
        selection = object_field(selection, path)
        if "listing_id" not in selection:
            raise ValueError(f"{path}.listing_id: required (null for no match)")
        identity = selection["listing_id"]
        listing = None
        if identity is not None:
            text_field(identity, f"{path}.listing_id")
            if identity not in by_id:
                raise ValueError(f"{path}.listing_id: unknown listing {identity}")
            listing = by_id[identity]
        slots.append({"slot": selection.get("slot"),
                      "matched_affixes": selection.get("matched_affixes"),
                      "listing": deepcopy(listing)})
    # Share the existing slot/context/price validation before returning a contract.
    aggregate_quotes(slots, realm=realm, league=league)
    return deepcopy({"context": {"realm": realm, "league": league}, "slots": slots})


def assemble_file(path: Path, worker=None):
    """Resolve a local raw-response file relative to the selection manifest.

    With a worker command the build is re-read through the pinned engine.
    """
    payload = object_field(json.loads(path.read_text(encoding="utf-8")), "input")
    context = object_field(payload.get("context"), "context")
    source = text_field(payload.get("response_file"), "response_file")
    response = json.loads((path.parent / source).read_text(encoding="utf-8"))
    listings = normalize_listings(response, **context)
    selections = payload.get("selections")
    build = None
    if "build_file" in payload:
        build_file = path.parent / text_field(payload["build_file"], "build_file")
        if worker:
            build = engine_build(build_file, worker)
        elif (payload.get("build") or {}).get("source") == "engine":
            raise ValueError("engine selections require the PoB worker command")
        else:
            build = extract_build(build_file)
        inventory = bind_selections(build, selections)
    result = assemble_quotes(listings, selections, **context)
    if build is not None:
        for row in result["slots"]:
            row["build_item"] = deepcopy(inventory[row["slot"]]["build_item"])
        result["build"] = build
    return result
