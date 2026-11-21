#!/usr/bin/env python3
"""Fetch the pinned PoB source into a new directory (Python 3 and Git)."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile


def fetch_source(manifest_path, destination):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    commit = manifest["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("manifest commit must be a full 40-character SHA")
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage beside the destination; failed fetches leave no partial checkout.
    with tempfile.TemporaryDirectory(prefix=".pob-fetch-", dir=destination.parent) as staging:
        source = Path(staging) / "source"

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(source), *args], text=True
            ).strip()

        subprocess.run(["git", "init", "--quiet", str(source)], check=True)
        git("remote", "add", "origin", manifest["repository"])
        git("fetch", "--depth=1", "--no-tags", "origin", commit)
        git("checkout", "--quiet", "--detach", "FETCH_HEAD")
        if git("rev-parse", "HEAD") != commit:
            raise ValueError("fetched HEAD does not match manifest commit")
        source.rename(destination)
    print(f"PoB {commit}: {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new source directory")
    args = parser.parse_args()
    manifest = Path(__file__).resolve().parents[1] / "sources" / "pob.json"
    try:
        fetch_source(manifest, args.destination)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"PoB source fetch failed: {error}\n")


if __name__ == "__main__":
    main()
