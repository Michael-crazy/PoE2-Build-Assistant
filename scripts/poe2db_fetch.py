#!/usr/bin/env python3
"""One fetcher for PoE2DB (编年史, poe2db.tw): shared page cache, manifest, 4 s between requests.

  python3 -B scripts/poe2db_fetch.py [--cache DIR] [--offline] pages Rings Keywords --langs us,cn,tw
  python3 -B scripts/poe2db_fetch.py gems              # every gem page linked from the gem index pages
  python3 -B scripts/poe2db_fetch.py adopt-gempages    # register the D02 gempages/{us,cn} files
  python3 -B scripts/poe2db_fetch.py status
  python3 -B scripts/poe2db_fetch.py --refresh-before 2026-12-12T05:30+08:00 refresh   # R03 new season
  python3 -B scripts/poe2db_fetch.py gems --index-max-age 1    # refetch the gem indexes only: new gems
  python3 -B scripts/poe2db_fetch.py --max-age 1 pages Rings   # refetch Rings if older than a day

R03 refresh: with `--max-age DAYS` / `--refresh-before ISO` (Fetcher(stale_before=...)), a cached page or
recorded 404 whose manifest time is before the limit is fetched again (same lock and 4 s spacing). A
fixed --refresh-before makes an interrupted refresh resumable: pages already fetched again are newer.
A page that now answers 404 is dropped from the cache; a 404 that answers again leaves missing[].

Every module that needs a PoE2DB page asks `Fetcher(cache).get(url)` (or `.page(lang, name)`):

- The cache manifest (`manifest.json`) is the index: `pages[]` (url, file, fetched) and `missing[]`
  (url, status). A page listed there and present on disk, or a recorded 404, never goes to the network.
- New pages are stored as `<lang>/<page>.html` (`https://poe2db.tw/cn/Rings` -> `cn/Rings.html`); a query
  string adds `@<sha1 of it>`; paths outside a language go to `site/`. Older layouts (D02's
  `gempages/<lang>/`) stay where they are and are found through the manifest.
- Network requests are serialized across processes with a lock file (`.fetch.lock`) and are at least
  `delay` (default 4) seconds apart, measured from the last request of any process (`.last_fetch`).
  A network error or 5xx waits 15 s and is retried once; a 404/410 is recorded in `missing[]`.
- `offline=True` (or POE2DB_OFFLINE=1) never touches the network: an uncached page is None.

Standard library only, so the U01 package and other repositories (POBG's zh_cn/shared_cache.py
implements the same layout) can use the same cache.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

SITE = "https://poe2db.tw"
HOST = "poe2db.tw"
LANGS = ("us", "cn", "tw")
AGENT = "Mozilla/5.0 (poe2-assistant; low-rate cache)"
DEFAULT_CACHE = Path.home() / ".local/state/poe2-assistant/poe2db-cache"
DELAY = 4.0
RETRY_WAIT = 15.0
GONE = (404, 410)
SAFE = "/_-.,()!~*'+:"
KEEP_SUFFIX = (".json", ".js", ".lua", ".txt", ".xml")
GEM_INDEXES = ("Skill_Gems", "Support_Gems", "Spirit_Gems", "Meta_Skill_Gem")
GEM_LINK = re.compile(r'<a class="gem[a-z_]*"[^>]*href="/us/([^"#?]+)"')
CST = timezone(timedelta(hours=8))


class FetchError(RuntimeError):
    """The page could not be fetched (network error or unexpected HTTP status) after the retry."""


def normalize(url):
    """Canonical form of a poe2db.tw URL: https, no fragment, path percent-encoded one way."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if host == "www." + HOST:
        host = HOST
    if host != HOST and not host.endswith("." + HOST):
        raise ValueError(f"not a PoE2DB URL: {url}")
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe=SAFE)
    return urllib.parse.urlunsplit(("https", host, path, parts.query, ""))


def page_url(lang, page):
    return normalize(f"{SITE}/{lang}/{page}")


def cache_path(url):
    """Relative cache file for a URL (new layout)."""
    parts = urllib.parse.urlsplit(normalize(url))
    path = urllib.parse.unquote(parts.path).strip("/")
    segments = path.split("/")
    if not path or any(s in ("", ".", "..") or "\\" in s or "\0" in s for s in segments):
        raise ValueError(f"unsafe PoE2DB path: {url}")
    if parts.hostname != HOST:
        rel = f"site/{parts.hostname}/{path}"
    else:
        rel = path if segments[0] in LANGS and len(segments) > 1 else f"site/{path}"
    if parts.query:
        rel += "@" + hashlib.sha1(parts.query.encode("utf-8")).hexdigest()[:16]
    return rel if rel.endswith(KEEP_SUFFIX) and not parts.query else rel + ".html"


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextmanager
def _locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(1 << 30)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.5)
            try:
                yield
            finally:
                handle.seek(1 << 30)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _open(url):
    """Default network call: (status, body bytes)."""
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


class Fetcher:
    def __init__(self, cache=DEFAULT_CACHE, delay=DELAY, offline=None, opener=_open, sleep=time.sleep,
                 clock=time.time, log=None, stale_before=None):
        self.cache = Path(cache).expanduser()
        # R03 refresh: cached pages and 404 records older than this (aware datetime) are fetched again.
        self.stale_before = stale_before
        self.delay = max(float(delay), DELAY)
        self.offline = os.environ.get("POE2DB_OFFLINE") == "1" if offline is None else offline
        self.opener, self.sleep, self.clock = opener, sleep, clock
        self.log = log or (lambda message: None)
        self.fetched = []          # (url, status) of this object's network requests
        self._index = None

    # -- manifest -------------------------------------------------------------
    def manifest(self):
        path = self.cache / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"source": SITE}
        data.setdefault("pages", [])
        data.setdefault("missing", [])
        return data

    def _load_index(self):
        manifest = self.manifest()
        pages, missing = {}, {}
        for entry in manifest["pages"]:
            try:
                pages[normalize(entry["url"])] = entry
            except (KeyError, ValueError):
                continue
        for entry in manifest["missing"]:
            try:
                missing[normalize(entry["url"])] = entry
            except (KeyError, ValueError):
                continue
        self._index = (pages, missing)
        return self._index

    def _update_manifest(self, page=None, missing=None, found=None):
        """Re-read, merge one record, write atomically (call with the fetch lock held)."""
        manifest = self.manifest()
        if found:  # a recorded 404 that exists again
            manifest["missing"] = [m for m in manifest["missing"] if not _same(m.get("url"), found)]
        if page:
            manifest["pages"] = [p for p in manifest["pages"] if _same(p.get("url"), page["url"]) is False] + [page]
        if missing:
            manifest["missing"] = [m for m in manifest["missing"] if _same(m.get("url"), missing["url"]) is False] + [missing]
        data = json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")
        _atomic_write(self.cache / "manifest.json", data)
        self._index = None

    # -- lookups --------------------------------------------------------------
    def cached_file(self, url):
        """Path of the cached copy of url, or None."""
        url = normalize(url)
        pages, _ = self._index or self._load_index()
        entry = pages.get(url)
        if entry and (self.cache / entry["file"]).exists():
            return self.cache / entry["file"]
        path = self.cache / cache_path(url)
        return path if path.exists() else None

    def is_missing(self, url):
        _, missing = self._index or self._load_index()
        entry = missing.get(normalize(url))
        return bool(entry) and entry.get("status") in GONE

    def get(self, url, refresh=False):
        """Page text (UTF-8), or None for a recorded 404 / an uncached page offline."""
        body = self.get_bytes(url, refresh)
        return None if body is None else body.decode("utf-8", errors="replace")

    def page(self, lang, page, refresh=False):
        return self.get(page_url(lang, page), refresh)

    def is_stale(self, url):
        """True when stale_before is set and the cached copy (or 404 record) of url is older than it.

        A file found only by its layout path (no manifest record) has no known age and counts as stale."""
        if self.stale_before is None:
            return False
        url = normalize(url)
        pages, missing = self._index or self._load_index()
        entry = pages.get(url)
        if entry and (self.cache / entry["file"]).exists():
            return _older(entry.get("fetched"), self.stale_before)
        if url in missing and missing[url].get("status") in GONE:
            return _older(missing[url].get("checked"), self.stale_before)
        return (self.cache / cache_path(url)).exists()

    def get_bytes(self, url, refresh=False):
        url = normalize(url)
        refresh = refresh or (not self.offline and self.is_stale(url))
        path = None if refresh else self.cached_file(url)
        if path:
            return path.read_bytes()
        if self.is_missing(url) and not refresh:
            return None
        if self.offline:
            return None
        return self._network(url, refresh)

    # -- network --------------------------------------------------------------
    def _network(self, url, refresh=False):
        with _locked(self.cache / ".fetch.lock"):
            if not refresh:
                self._index = None             # another process may have fetched it while we waited
                if not self.is_stale(url):
                    path = self.cached_file(url)
                    if path:
                        return path.read_bytes()
                    if self.is_missing(url):
                        return None
            status, body = self._request(url)
            if status in GONE:
                old = self._drop_page(url)     # a page that went away: forget the stale copy
                self._update_manifest(missing={"url": url, "status": status, "checked": _stamp()})
                if old:
                    old.unlink(missing_ok=True)
                return None
            rel = cache_path(url)
            _atomic_write(self.cache / rel, body)
            self._update_manifest(page={"url": url, "file": rel, "fetched": _stamp()}, found=url)
            return body

    def _drop_page(self, url):
        """Remove url's page record (lock held); returns the file it pointed to, if any."""
        manifest = self.manifest()
        old = [p for p in manifest["pages"] if _same(p.get("url"), url)]
        path = self.cache / old[0]["file"] if old else self.cache / cache_path(url)
        if old:
            manifest["pages"] = [p for p in manifest["pages"] if not _same(p.get("url"), url)]
            _atomic_write(self.cache / "manifest.json",
                          json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
            self._index = None
        return path if path.exists() else None

    def _request(self, url):
        last = self.cache / ".last_fetch"
        for attempt in (1, 2):
            try:
                previous = float(last.read_text().strip() or 0) if last.exists() else 0.0
            except ValueError:
                previous = 0.0
            wait = previous + self.delay - self.clock()
            if wait > 0:
                self.sleep(wait)
            try:
                status, body = self.opener(url)
                error = None if status == 200 or status in GONE else f"HTTP {status}"
            except Exception as exc:  # network failure: wait and retry once
                status, body, error = None, b"", f"{type(exc).__name__}: {exc}"
            finally:
                _atomic_write(last, f"{self.clock():.3f}\n".encode())
            self.fetched.append((url, status))
            self.log(f"{status or 'ERR'} {url}")
            if error is None:
                return status, body
            if attempt == 1 and (status is None or status >= 500 or status == 429):
                self.sleep(RETRY_WAIT)
                continue
            raise FetchError(f"{url}: {error}")

    # -- maintenance ----------------------------------------------------------
    def adopt(self, rel_files, url_for):
        """Register existing cache files (relative paths) in the manifest without fetching."""
        with _locked(self.cache / ".fetch.lock"):
            manifest = self.manifest()
            known = {normalize(p["url"]) for p in manifest["pages"] if p.get("url")}
            added = 0
            for rel in rel_files:
                url = normalize(url_for(rel))
                if url in known:
                    continue
                mtime = datetime.fromtimestamp((self.cache / rel).stat().st_mtime, CST)
                manifest["pages"].append({"url": url, "file": rel, "fetched": mtime.isoformat(timespec="minutes"),
                                          "adopted": True})
                known.add(url)
                added += 1
            if added:
                _atomic_write(self.cache / "manifest.json",
                              json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
            self._index = None
            return added


def _same(left, right):
    try:
        return normalize(left) == normalize(right)
    except (TypeError, ValueError):
        return False


def _stamp():
    return datetime.now(CST).isoformat(timespec="seconds")


def _older(stamp, limit):
    """True when the ISO time `stamp` is before `limit`; a missing or unreadable stamp is old."""
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=CST)
    return when < limit


def parse_limit(max_age=None, refresh_before=None, now=None):
    """stale_before from --max-age DAYS and/or --refresh-before ISO (the later one wins), or None."""
    limits = []
    if max_age is not None:
        limits.append((now or datetime.now(CST)) - timedelta(days=float(max_age)))
    if refresh_before:
        when = datetime.fromisoformat(refresh_before)
        limits.append(when if when.tzinfo else when.replace(tzinfo=CST))
    return max(limits) if limits else None


def gem_pages(fetcher):
    """Gem page names linked from the English gem index pages."""
    names = set()
    for index in GEM_INDEXES:
        names.update(GEM_LINK.findall(fetcher.page("us", index) or ""))
    return sorted(urllib.parse.unquote(name) for name in names)


def fetch_pages(fetcher, pages, langs=LANGS):
    """Fetch (or find in the cache) every page in every language; returns {'ok','missing','failed'}."""
    result = {"ok": 0, "missing": [], "failed": []}
    for page in pages:
        for lang in langs:
            url = page_url(lang, page)
            try:
                found = fetcher.get(url)
            except FetchError as error:
                result["failed"].append(str(error))
                continue
            if found is None:
                result["missing"].append(url)
            else:
                result["ok"] += 1
    return result


def stale_urls(fetcher):
    """Manifest URLs (pages, then 404s) older than fetcher.stale_before, in manifest order."""
    manifest = fetcher.manifest()
    urls = []
    for entry in manifest["pages"] + manifest["missing"]:
        try:
            url = normalize(entry["url"])
        except (KeyError, ValueError):
            continue
        if url not in urls and fetcher.is_stale(url):
            urls.append(url)
    return urls


def refresh_all(fetcher):
    """R03 new-season refresh: refetch every stale page; returns {'refreshed','gone','failed','left'}."""
    result = {"refreshed": 0, "gone": [], "failed": []}
    urls = stale_urls(fetcher)
    for url in urls:
        try:
            found = fetcher.get(url)
        except FetchError as error:
            result["failed"].append(str(error))
            continue
        if found is None:
            result["gone"].append(url)
        else:
            result["refreshed"] += 1
    result["left"] = len(stale_urls(fetcher)) if not fetcher.offline else len(urls)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--offline", action="store_true", help="never use the network")
    parser.add_argument("--delay", type=float, default=DELAY, help="seconds between requests (minimum 4)")
    sub = parser.add_subparsers(dest="command", required=True)
    pages = sub.add_parser("pages", help="fetch pages by name")
    pages.add_argument("names", nargs="+")
    pages.add_argument("--langs", default=",".join(LANGS))
    gems = sub.add_parser("gems", help="fetch every gem page (us, cn)")
    gems.add_argument("--langs", default="us,cn")
    gems.add_argument("--index-max-age", type=float, metavar="DAYS",
                      help="refetch only the gem index pages older than DAYS (finds new gems)")
    sub.add_parser("refresh", help="refetch every page and 404 in the manifest older than the limit "
                                   "(needs --max-age or --refresh-before)")
    sub.add_parser("adopt-gempages", help="register gempages/<lang>/*.html in the manifest")
    sub.add_parser("status")
    parser.add_argument("--max-age", type=float, metavar="DAYS",
                        help="refetch cached pages (and 404s) fetched more than DAYS ago")
    parser.add_argument("--refresh-before", metavar="ISO",
                        help="refetch cached pages fetched before this time (fixed limit: an interrupted "
                             "refresh run again with the same limit fetches only what is left)")
    args = parser.parse_args(argv)
    limit = parse_limit(args.max_age, args.refresh_before)
    log = lambda m: print(m, flush=True)  # noqa: E731
    fetcher = Fetcher(args.cache, args.delay, args.offline or None, log=log, stale_before=limit)
    if args.command == "pages":
        result = fetch_pages(fetcher, args.names, args.langs.split(","))
    elif args.command == "gems":
        index = fetcher
        if args.index_max_age is not None:
            index = Fetcher(args.cache, args.delay, args.offline or None, log=log,
                            stale_before=parse_limit(args.index_max_age))
            index.fetched = fetcher.fetched
        result = fetch_pages(fetcher, gem_pages(index), args.langs.split(","))
    elif args.command == "refresh":
        if limit is None:
            parser.error("refresh needs --max-age or --refresh-before")
        result = refresh_all(fetcher)
    elif args.command == "adopt-gempages":
        files = sorted(str(p.relative_to(fetcher.cache)).replace(os.sep, "/")
                       for p in (fetcher.cache / "gempages").glob("*/*.html"))
        result = {"adopted": fetcher.adopt(files, lambda rel: f"{SITE}/{rel.split('/')[1]}/{rel.split('/', 2)[2][:-5]}"),
                  "files": len(files)}
    else:
        manifest = fetcher.manifest()
        result = {"pages": len(manifest["pages"]), "missing": len(manifest["missing"]),
                  "on_disk": sum(1 for p in manifest["pages"] if (fetcher.cache / p["file"]).exists())}
        if limit is not None:
            result["stale"] = len(stale_urls(fetcher))
    result["network_requests"] = len(fetcher.fetched)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
