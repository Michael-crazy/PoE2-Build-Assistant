#!/usr/bin/env python3
"""Privacy check for files that go public: run it on the repository (or an export) before every push.

    python3 -B ops/check_public.py [DIR] [--terms FILE] [--max-size MIB] [--json]

Scans every file under DIR (default: the repository root; .git is skipped) for
  - WeGame share links/codes, openid, account/nick names, role ids, share codes left in JSON
    (allowed values: "<removed>", "", short placeholder role ids such as "1");
  - login cookies with values (POESESSID, QQ/WeGame cookies such as p_skey, skey, uin, pt4_token)
    and Cookie: headers;
  - local paths: Windows user folders (C:\\Users\\...), /home/<user>/, /Users/<user>/;
  - e-mail addresses (except noreply/example addresses);
  - extra literal terms (host names, user names) read from --terms, one per line, case-insensitive.
    The default terms file ops/public-check-terms.txt is optional and never published;
  - files larger than --max-size MiB (default 10; GitHub warns at 50, refuses 100).
Exit code 1 when anything is found. Binary files only get the size check.
"""

import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
TERMS = ROOT / "ops/public-check-terms.txt"
SKIP_DIRS = {".git", "__pycache__", "node_modules"}

PLACEHOLDER = r'(?:<removed>|)'
PATTERNS = [
    ("share_link", re.compile(r"#/share/(?!<)[A-Za-z0-9_-]{16,}")),
    ("json_private_field", re.compile(
        r'"(?:openid|share_code|account_name|nick_name|accountName|nickname)"\s*:\s*"(?!' + PLACEHOLDER + r'")[^"]+"')),
    ("role_id", re.compile(r'"role_?id"\s*:\s*"?\d{4,}')),
    ("poesessid", re.compile(r"POESESSID\s*[=:]\s*[\"']?[0-9a-fA-F]{20,}")),
    ("login_cookie", re.compile(r"\b(?:p_skey|skey|p_uin|pt4_token|pt_key|uin|tgp_ticket|tgp_id)=(?!<|\{|\$|%|\"|')[^;\s\"'&]{4,}")),
    ("cookie_header", re.compile(r"(?i)\bcookie:\s*[A-Za-z0-9_]+=(?!<)[^;\s\"']{8,}")),
    ("windows_user_path", re.compile(r"(?i)\b[A-Z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)(?!<|%|…|Public\b|Default\b|you\b|name\b|USERNAME\b|\.\.\.)[^\\/\s\"'`<>]+")),
    ("home_path", re.compile(r"(?<![\w.])/home/(?!<|\$|user\b|runner\b|USER\b|\.\.\.)[a-z_][a-z0-9_-]*")),
    ("mac_user_path", re.compile(r"(?<![\w.:])/Users/(?!<|\$|Shared\b|you\b|name\b)[A-Za-z][A-Za-z0-9_-]*")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]
ALLOWED_EMAIL = re.compile(
    r"(?i)^(?:noreply@anthropic\.com|git@github\.com|[\w.+-]*noreply@[\w.-]+|[\w.+-]+@(?:example\.(?:com|org|net)|[\w.-]*\.?(?:invalid|test|example)|users\.noreply\.github\.com))$")


def load_terms(path):
    if not path or not Path(path).is_file():
        return []
    terms = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def iter_files(root):
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            yield Path(folder) / name


def scan_text(text, terms=()):
    """Findings in one text: list of (kind, line number, matched text)."""
    found = []
    lowered_terms = [(t, t.lower()) for t in terms]
    for number, line in enumerate(text.splitlines(), 1):
        for kind, pattern in PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                if kind == "email" and ALLOWED_EMAIL.match(value):
                    continue
                found.append((kind, number, value))
        low = line.lower()
        for term, lowered in lowered_terms:
            if lowered in low:
                found.append(("private_term", number, term))
    return found


def check(root, terms=(), max_bytes=10 * 1024 * 1024):
    root = Path(root)
    findings = []
    files = 0
    for path in iter_files(root):
        files += 1
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            continue
        size = path.stat().st_size
        if size > max_bytes:
            findings.append({"file": rel, "kind": "large_file", "line": 0, "match": f"{size / 1048576:.1f} MiB"})
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        for kind, line, match in scan_text(text, terms):
            findings.append({"file": rel, "kind": kind, "line": line, "match": match[:120]})
        for term in terms:  # file names can leak too
            if term.lower() in rel.lower():
                findings.append({"file": rel, "kind": "private_term_in_path", "line": 0, "match": term})
    return files, findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dir", nargs="?", type=Path, default=ROOT)
    parser.add_argument("--terms", type=Path, default=TERMS)
    parser.add_argument("--max-size", type=float, default=10, help="MiB")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    files, findings = check(args.dir, load_terms(args.terms), int(args.max_size * 1024 * 1024))
    if args.json:
        json.dump({"files": files, "findings": findings}, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        for f in findings:
            print(f"{f['file']}:{f['line']}: {f['kind']}: {f['match']}")
        print(f"{files} files, {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
