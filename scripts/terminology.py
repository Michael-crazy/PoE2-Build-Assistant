#!/usr/bin/env python3
"""Offline, version-scoped terminology catalog. No PoB or network dependency."""

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import unicodedata


LOCALES = ("en", "zh-Hans", "zh-Hant")
KINDS = ("skill", "passive", "item", "mod")
ROOT = Path(__file__).resolve().parents[1]


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected a nonempty string")
    return value


def normalize(value):
    return " ".join(unicodedata.normalize("NFC", text(value)).casefold().split())


@dataclass(frozen=True)
class Term:
    id: str
    kind: str
    aliases: dict
    source: str


class Catalog:
    def __init__(self, data, *, engine_commit, data_version):
        if data.get("schema") != "poe2-terminology/1":
            raise ValueError("unsupported terminology schema")
        if data.get("engine_commit") != engine_commit:
            raise ValueError("terminology engine_commit mismatch")
        if data.get("data_version") != data_version:
            raise ValueError("terminology data_version mismatch")
        self.engine_commit = text(engine_commit)
        self.data_version = text(data_version)
        self.sources = data.get("sources")
        if not isinstance(self.sources, dict) or not self.sources:
            raise ValueError("catalog requires source records")
        for key, source in self.sources.items():
            text(key)
            if not isinstance(source, dict):
                raise ValueError("invalid source record")
            for field in ("origin", "license", "verification"):
                text(source.get(field))
        if not isinstance(data.get("entries"), list):
            raise ValueError("entries must be a list")
        self._ids = {}
        self._aliases = {}
        for row in data["entries"]:
            if not isinstance(row, dict):
                raise ValueError("invalid term record")
            identifier = text(row.get("id"))
            kind = row.get("kind")
            aliases = row.get("aliases")
            source = row.get("source")
            if identifier in self._ids:
                raise ValueError(f"duplicate ID: {identifier}")
            if kind not in KINDS:
                raise ValueError(f"invalid kind: {kind}")
            if not isinstance(source, str) or source not in self.sources:
                raise ValueError(f"unknown source for {identifier}")
            if not isinstance(aliases, dict) or set(aliases) != set(LOCALES):
                raise ValueError(f"expected en/zh-Hans/zh-Hant aliases for {identifier}")
            clean = {}
            for locale, names in aliases.items():
                if not isinstance(names, list) or not names:
                    raise ValueError(f"missing aliases for {identifier}/{locale}")
                clean[locale] = tuple(text(name) for name in names)
                for name in names:
                    self._aliases.setdefault(normalize(name), set()).add(identifier)
            self._ids[identifier] = Term(identifier, kind, clean, source)

    @classmethod
    def load(cls, path, *, engine_commit, data_version):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("catalog must be a JSON object")
        return cls(data, engine_commit=engine_commit, data_version=data_version)

    def by_id(self, identifier):
        """Exact ID lookup; IDs are never translated or case-folded."""
        return self._ids.get(text(identifier))

    def lookup(self, alias, *, kind=None):
        """Return all candidates; shared aliases never silently select an ID."""
        if kind is not None and kind not in KINDS:
            raise ValueError(f"invalid kind: {kind}")
        return tuple(self._ids[key] for key in sorted(self._aliases.get(normalize(alias), ()))
                     if kind is None or self._ids[key].kind == kind)


def main():
    parser = argparse.ArgumentParser(description="离线版本化术语查找")
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--data-version", required=True)
    query = parser.add_mutually_exclusive_group(required=True)
    query.add_argument("--id")
    query.add_argument("--alias")
    parser.add_argument("--kind", choices=KINDS, help="别名查询的类别")
    args = parser.parse_args()
    if args.id is not None and args.kind is not None:
        parser.error("--kind 仅用于 --alias")
    try:
        pin = json.loads((ROOT / "sources/pob.json").read_text(encoding="utf-8"))
        catalog = Catalog.load(args.catalog, engine_commit=pin["commit"],
                               data_version=args.data_version)
        if args.id is not None:
            term = catalog.by_id(args.id)
            matches = (term,) if term else ()
        else:
            matches = catalog.lookup(args.alias, kind=args.kind)
    except (OSError, ValueError) as error:
        parser.exit(1, f"术语查找失败：{error}\n")
    status = "not_found" if not matches else "found" if len(matches) == 1 else "ambiguous"
    print(json.dumps({"schema": "poe2-terminology/1", "engine_commit": catalog.engine_commit,
                      "data_version": catalog.data_version, "status": status,
                      "matches": [asdict(term) for term in matches],
                      "sources": catalog.sources}, ensure_ascii=False, indent=2))
    return {"found": 0, "not_found": 2, "ambiguous": 3}[status]


if __name__ == "__main__":
    raise SystemExit(main())
