#!/usr/bin/env python3
"""Lossless offline clipboard inspection with caller-declared synthetic mod sections."""

import argparse
import json
from pathlib import Path
import re

NUMBER = r"[+-]?[0-9]+(?:\.[0-9]+)?"


def inspect_clipboard(text, profile):
    """Retain exact text; synthetic IDs are diagnostics, never engine translations."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("clipboard: expected non-empty text")
    if not isinstance(profile, dict) or profile.get("scope") != "authored_synthetic":
        raise ValueError("profile: only authored_synthetic scope is supported")
    rules = profile.get("rules")
    if not isinstance(rules, list):
        raise ValueError("rules: expected array")
    compiled = []
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("rule: expected object")
        identity, template = rule.get("id"), rule.get("template")
        if (not isinstance(identity, str) or not identity.startswith("synthetic.")
                or identity in ids or not isinstance(template, str) or not template.strip()):
            raise ValueError("rule: expected unique synthetic ID and non-empty template")
        ids.add(identity)
        pattern = "(" + NUMBER + ")"
        compiled.append((identity, re.compile(pattern.join(
            re.escape(part) for part in template.split("{number}")))))

    # Keep terminators and blank lines: no whitespace cleanup or numeric conversion.
    sections = [{"index": 0, "lines": []}]
    separators = []
    for line_number, raw in enumerate(text.splitlines(keepends=True), 1):
        body = raw.rstrip("\r\n")
        row = {"line": line_number, "raw": raw, "text": body}
        if body == "--------":
            separators.append(row)
            sections.append({"index": len(sections), "lines": []})
        else:
            sections[-1]["lines"].append(row)
    mod_sections = profile.get("mod_sections")
    if (not isinstance(mod_sections, list) or not mod_sections
            or any(type(index) is not int or not 0 <= index < len(sections)
                   for index in mod_sections) or len(set(mod_sections)) != len(mod_sections)):
        raise ValueError("mod_sections: expected unique existing zero-based section indexes")
    matches, issues = [], []
    for index in mod_sections:
        for row in sections[index]["lines"]:
            if not row["text"].strip():
                continue
            found = [(identity, match.groups()) for identity, pattern in compiled
                     if (match := pattern.fullmatch(row["text"]))]
            location = {"section": index, "line": row["line"], "text": row["text"]}
            if len(found) == 1:
                identity, values = found[0]
                matches.append({**location, "id": identity, "numbers": list(values)})
            else:
                issues.append({**location, "code": "unmatched_mod" if not found else "ambiguous_mod",
                               "message": "词缀未匹配" if not found else "词缀匹配到多条规则"})
    return {"scope": "authored_synthetic", "raw_text": text, "sections": sections,
            "separators": separators, "mod_sections": list(mod_sections),
            "matches": matches, "issues": issues, "pob_import": "pending"}


def main():
    parser = argparse.ArgumentParser(description="离线检查自编中文装备剪贴板；不生成生产译文")
    parser.add_argument("input", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    try:
        # newline='' prevents CRLF normalization on read.
        with args.input.open(encoding="utf-8", newline="") as source:
            text = source.read()
        result = inspect_clipboard(text, json.loads(args.profile.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        parser.exit(1, f"无法检查装备文本：{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
