"""Preserve valid UTF-8 clipboard input in the pinned PoB edit control."""

import argparse
from pathlib import Path


LEGACY = 'text = text:gsub("[\\128-\\255]","?")'
UTF8_CLIPBOARD = (
    'if not utf8.isvalid(text) then\n'
    '\t\t\t\ttext = text:gsub("[\\128-\\255]", "?")\n'
    '\t\t\tend'
)


def patch_edit_control(path):
    source = path.read_bytes()
    legacy = LEGACY.encode("ascii")
    updated = UTF8_CLIPBOARD
    if b"\r\n" in source:
        updated = updated.replace("\n", "\r\n")
    replacement = updated.encode("ascii")
    if source.count(replacement) == 1 and legacy not in source:
        return
    if source.count(legacy) != 1:
        raise ValueError("Expected exactly one pinned PoB clipboard sanitizer")
    path.write_bytes(source.replace(legacy, replacement, 1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    args = parser.parse_args()
    patch_edit_control(args.engine / "src/Classes/EditControl.lua")
