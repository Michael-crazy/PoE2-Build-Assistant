import json
from pathlib import Path
import tempfile
import unittest

import poe2db_fetch as pf


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


class Site:
    def __init__(self, pages, clock, fail_first=()):
        self.pages, self.clock, self.calls = pages, clock, []
        self.fail_first = set(fail_first)

    def __call__(self, url):
        self.calls.append((url, self.clock.now))
        if url in self.fail_first:
            self.fail_first.discard(url)
            raise OSError("connection reset")
        if url in self.pages:
            return 200, self.pages[url].encode()
        return 404, b""


def fetcher(cache, site, clock, **kw):
    return pf.Fetcher(cache, opener=site, sleep=clock.sleep, clock=clock.time, **kw)


class PathTests(unittest.TestCase):
    def test_layout(self):
        self.assertEqual(pf.cache_path("https://poe2db.tw/cn/Rings"), "cn/Rings.html")
        self.assertEqual(pf.cache_path("https://poe2db.tw/us/Alchemist%27s_Genius"), "us/Alchemist's_Genius.html")
        self.assertEqual(pf.cache_path("https://poe2db.tw/data/passive-skill-tree/4.5/data_us.json"),
                         "site/data/passive-skill-tree/4.5/data_us.json")
        self.assertEqual(pf.cache_path("https://cdn.poe2db.tw/js/a.js"), "site/cdn.poe2db.tw/js/a.js")
        self.assertRegex(pf.cache_path("https://poe2db.tw/us/hover?t=x&c=1"), r"^us/hover@[0-9a-f]{16}\.html$")
        self.assertEqual(pf.normalize("http://poe2db.tw/us/Alchemist's_Genius#x"),
                         pf.normalize("https://poe2db.tw/us/Alchemist%27s_Genius"))
        for bad in ("https://example.com/us/Rings", "https://poe2db.tw/us/../x"):
            with self.assertRaises(ValueError):
                pf.cache_path(bad)


class FetcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        self.clock = Clock()
        self.site = Site({"https://poe2db.tw/us/Rings": "<title>Rings - x</title>",
                          "https://poe2db.tw/cn/Rings": "<title>戒指 - x</title>"}, self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self):
        return json.loads((self.cache / "manifest.json").read_text(encoding="utf-8"))

    def test_fetch_once_then_cache(self):
        f = fetcher(self.cache, self.site, self.clock)
        self.assertIn("戒指", f.page("cn", "Rings"))
        self.assertIn("戒指", f.page("cn", "Rings"))
        self.assertEqual(len(self.site.calls), 1)
        self.assertEqual((self.cache / "cn/Rings.html").read_text(encoding="utf-8"), "<title>戒指 - x</title>")
        self.assertEqual([p["file"] for p in self.manifest()["pages"]], ["cn/Rings.html"])
        again = fetcher(self.cache, self.site, self.clock)
        self.assertIsNotNone(again.page("cn", "Rings"))
        self.assertEqual(len(self.site.calls), 1)

    def test_requests_four_seconds_apart_across_fetchers(self):
        fetcher(self.cache, self.site, self.clock).page("us", "Rings")
        fetcher(self.cache, self.site, self.clock).page("cn", "Rings")   # a second process, same cache
        (first, t1), (second, t2) = self.site.calls
        self.assertGreaterEqual(t2 - t1, 4.0)

    def test_delay_never_below_four(self):
        self.assertEqual(pf.Fetcher(self.cache, delay=1).delay, 4.0)

    def test_404_recorded_and_not_retried(self):
        f = fetcher(self.cache, self.site, self.clock)
        self.assertIsNone(f.page("us", "Nope"))
        self.assertIsNone(fetcher(self.cache, self.site, self.clock).page("us", "Nope"))
        self.assertEqual(len(self.site.calls), 1)
        self.assertEqual(self.manifest()["missing"][0]["status"], 404)

    def test_offline_never_fetches(self):
        f = fetcher(self.cache, self.site, self.clock, offline=True)
        self.assertIsNone(f.page("us", "Rings"))
        self.assertEqual(self.site.calls, [])

    def test_network_error_retried_once(self):
        self.site.fail_first = {"https://poe2db.tw/us/Rings"}
        f = fetcher(self.cache, self.site, self.clock)
        self.assertIsNotNone(f.page("us", "Rings"))
        self.assertEqual(len(self.site.calls), 2)
        self.assertIn(pf.RETRY_WAIT, self.clock.slept)

    def test_server_error_raises_after_retry(self):
        f = fetcher(self.cache, lambda url: (503, b""), self.clock)
        with self.assertRaises(pf.FetchError):
            f.page("us", "Rings")
        self.assertFalse((self.cache / "us/Rings.html").exists())
        self.assertEqual(self.manifest()["missing"] if (self.cache / "manifest.json").exists() else [], [])

    def test_existing_manifest_kept_and_legacy_files_found(self):
        (self.cache / "gempages/us").mkdir(parents=True)
        (self.cache / "gempages/us/Fireball.html").write_text("fire", encoding="utf-8")
        (self.cache / "manifest.json").write_text(json.dumps({"source": "x", "site_version": "1.0", "pages": [
            {"url": "https://poe2db.tw/us/Fireball", "file": "gempages/us/Fireball.html", "fetched": "t"}]}),
            encoding="utf-8")
        f = fetcher(self.cache, self.site, self.clock)
        self.assertEqual(f.page("us", "Fireball"), "fire")
        f.page("us", "Rings")
        manifest = self.manifest()
        self.assertEqual(manifest["site_version"], "1.0")
        self.assertEqual(len(manifest["pages"]), 2)
        self.assertEqual(len(self.site.calls), 1)

    def test_adopt(self):
        (self.cache / "gempages/cn").mkdir(parents=True)
        (self.cache / "gempages/cn/Fireball.html").write_text("火球", encoding="utf-8")
        f = fetcher(self.cache, self.site, self.clock)
        self.assertEqual(f.adopt(["gempages/cn/Fireball.html"], lambda rel: "https://poe2db.tw/cn/Fireball"), 1)
        self.assertEqual(f.adopt(["gempages/cn/Fireball.html"], lambda rel: "https://poe2db.tw/cn/Fireball"), 0)
        self.assertEqual(f.page("cn", "Fireball"), "火球")
        self.assertEqual(self.site.calls, [])

    def test_refresh_refetches(self):
        f = fetcher(self.cache, self.site, self.clock)
        f.page("us", "Rings")
        f.page("us", "Rings", refresh=True)
        self.assertEqual(len(self.site.calls), 2)
        self.assertEqual(len(self.manifest()["pages"]), 1)


class RefreshTests(unittest.TestCase):
    """R03: refetch only pages older than the limit."""
    setUp, tearDown, manifest = FetcherTests.setUp, FetcherTests.tearDown, FetcherTests.manifest

    def age(self, url, stamp, key="pages", field="fetched"):
        manifest = self.manifest()
        for entry in manifest[key]:
            if entry["url"] == url:
                entry[field] = stamp
        (self.cache / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def limit(self):
        return pf.parse_limit(refresh_before="2026-02-01T00:00:00+08:00")

    def test_only_stale_pages_refetched(self):
        f = fetcher(self.cache, self.site, self.clock)
        f.page("us", "Rings")
        f.page("cn", "Rings")
        self.age("https://poe2db.tw/us/Rings", "2026-01-01T10:00+08:00")
        self.age("https://poe2db.tw/cn/Rings", "2026-03-02T10:00:00+08:00")
        self.site.pages["https://poe2db.tw/us/Rings"] = "<title>Rings v2</title>"
        g = fetcher(self.cache, self.site, self.clock, stale_before=self.limit())
        self.assertEqual(pf.stale_urls(g), ["https://poe2db.tw/us/Rings"])
        self.assertEqual(g.page("us", "Rings"), "<title>Rings v2</title>")
        self.assertIn("戒指", g.page("cn", "Rings"))
        self.assertEqual([u for u, _ in g.fetched], ["https://poe2db.tw/us/Rings"])
        # the refreshed page is newer than the limit: a second pass (resume) fetches nothing
        h = fetcher(self.cache, self.site, self.clock, stale_before=self.limit())
        self.assertEqual(pf.refresh_all(h), {"refreshed": 0, "gone": [], "failed": [], "left": 0})
        self.assertEqual(h.fetched, [])

    def test_refresh_all_resumes_and_handles_gone(self):
        f = fetcher(self.cache, self.site, self.clock)
        f.page("us", "Rings")
        f.page("cn", "Rings")
        f.page("us", "Nope")
        for url in ("https://poe2db.tw/us/Rings", "https://poe2db.tw/cn/Rings"):
            self.age(url, "2026-01-01T10:00+08:00")
        self.age("https://poe2db.tw/us/Nope", "2026-01-01T10:00+08:00", "missing", "checked")
        del self.site.pages["https://poe2db.tw/cn/Rings"]          # removed upstream
        self.site.pages["https://poe2db.tw/us/Nope"] = "new gem"   # appeared
        g = fetcher(self.cache, self.site, self.clock, stale_before=self.limit())
        result = pf.refresh_all(g)
        self.assertEqual(result["refreshed"], 2)
        self.assertEqual(result["gone"], ["https://poe2db.tw/cn/Rings"])
        self.assertEqual(result["left"], 0)
        manifest = self.manifest()
        self.assertEqual(sorted(p["url"] for p in manifest["pages"]),
                         ["https://poe2db.tw/us/Nope", "https://poe2db.tw/us/Rings"])
        self.assertEqual([m["url"] for m in manifest["missing"]], ["https://poe2db.tw/cn/Rings"])
        self.assertFalse((self.cache / "cn/Rings.html").exists())
        self.assertTrue(all(a >= 4 for a in self.clock.slept))

    def test_offline_serves_stale_copy(self):
        f = fetcher(self.cache, self.site, self.clock)
        f.page("us", "Rings")
        self.age("https://poe2db.tw/us/Rings", "2026-01-01T10:00+08:00")
        g = fetcher(self.cache, self.site, self.clock, offline=True, stale_before=self.limit())
        self.assertIn("Rings", g.page("us", "Rings"))
        self.assertEqual(len(self.site.calls), 1)

    def test_parse_limit(self):
        now = pf.datetime(2026, 12, 10, tzinfo=pf.CST)
        self.assertIsNone(pf.parse_limit())
        self.assertEqual(pf.parse_limit(max_age=2, now=now), pf.datetime(2026, 12, 8, tzinfo=pf.CST))
        self.assertEqual(pf.parse_limit(max_age=30, refresh_before="2026-12-05T00:00", now=now),
                         pf.datetime(2026, 12, 5, tzinfo=pf.CST))

    def test_gem_index_refresh_finds_new_gems(self):
        index = "https://poe2db.tw/us/Skill_Gems"
        self.site.pages[index] = '<a class="gem_red" href="/us/Fireball">'
        self.site.pages["https://poe2db.tw/us/Fireball"] = "fire"
        self.site.pages["https://poe2db.tw/us/Frost_Bomb"] = "frost"
        f = fetcher(self.cache, self.site, self.clock)
        pf.fetch_pages(f, pf.gem_pages(f), ["us"])
        self.age(index, "2026-01-01T10:00+08:00")
        self.age("https://poe2db.tw/us/Fireball", "2026-01-01T10:00+08:00")
        self.site.pages[index] += '<a class="gem_blue" href="/us/Frost_Bomb">'
        calls = len(self.site.calls)
        g = fetcher(self.cache, self.site, self.clock)
        idx = fetcher(self.cache, self.site, self.clock, stale_before=self.limit())
        pf.fetch_pages(g, pf.gem_pages(idx), ["us"])
        fetched = [u for u, _ in self.site.calls[calls:]]
        self.assertIn(index, fetched)
        self.assertIn("https://poe2db.tw/us/Frost_Bomb", fetched)
        self.assertNotIn("https://poe2db.tw/us/Fireball", fetched)   # old gem page stays cached


if __name__ == "__main__":
    unittest.main()
