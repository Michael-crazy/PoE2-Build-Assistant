import unittest

import ui_fallback_prep as prep


class NormalizeTests(unittest.TestCase):
    def test_placeholders_and_colours_share_one_key(self):
        self.assertEqual(prep.normalize("^7Requires Level %d"), "Requires Level {#}")
        self.assertEqual(prep.normalize("Requires Level {0}"), "Requires Level {#}")
        self.assertEqual(prep.normalize("^xFF7700Recovers %.1f Mana  over %s"), "Recovers {#} Mana over {#}")

    def test_only_drawn_text_is_kept(self):
        for text in ("Craft Item", "Any slot", "Requires Level %d", "Del All"):
            self.assertTrue(prep.looks_like_text(text), text)
        for text in ("mainSkill", "Data.Gems", "FireMin", "Condition:Moving", "{0:output:WardPercentCost}", "%d+"):
            self.assertFalse(prep.looks_like_text(text), text)

    def test_lua_pairs_and_terms(self):
        pairs = prep.lua_pairs('return {\n\t["Craft \\"Item\\""] = "制作物品",\n}')
        self.assertEqual(pairs, {'Craft "Item"': "制作物品"})
        hits = prep.term_hits("Enable the Chaotic Might buff", {"chaotic might": "混沌之力", "might": "力量"})
        self.assertEqual(hits, [("chaotic might", "混沌之力")])

    def test_review_entries_are_sorted(self):
        terms = {"cold snap": "冰霜闪现", "eye of winter": "凛冬之眼", "cold": "冰霜", "perforate": "穿刺"}
        learned = prep.conflicts([{"key": "Cold Snap", "zh": "霜爆"}], terms)
        self.assertEqual(learned, {"霜爆": "冰霜闪现"})
        cases = [
            ({"key": "Cold Snap", "zh": "霜爆", "review": [{"term": "cold snap", "poe2db": "冰霜闪现"}]},
             "fixed_exact", "冰霜闪现"),
            ({"key": "See All", "zh": "查看全部", "review": [{"term": "see all", "poe2db": None}]}, "likely_ui", "查看全部"),
            ({"key": "Perforates", "zh": "穿孔", "review": [{"term": "perforates", "poe2db": None}]}, "manual", "穿孔"),
            ({"key": "Eye of Winter has passed over Cold Ground", "zh": "Eye of Winter 已通過冰霜地面",
              "review": [{"term": "eye of winter", "poe2db": "凛冬之眼"}]}, "fixed_sub", "凛冬之眼 已通過冰霜地面"),
            ({"key": "Use Cold Snap now", "zh": "立即使用霜爆", "review": [{"term": "cold snap", "poe2db": "冰霜闪现"}]},
             "fixed_sub", "立即使用冰霜闪现"),
            ({"key": "Cold damage taken", "zh": "承受寒冷伤害", "review": [{"term": "cold", "poe2db": "冰霜"}]},
             "manual", "承受寒冷伤害"),
        ]
        cases.append(({"key": "Seismic Trap", "zh": "震波陷阱", "review": [{"term": "seismic trap", "poe2db": None}]},
                      "manual", "震波陷阱"))
        for entry, status, zh in cases:
            prep.classify(entry, terms, learned, {"seismic trap"})
            self.assertEqual((entry["status"], entry["zh"]), (status, zh), entry["key"])

    def test_site_kinds(self):
        self.assertEqual(prep.site_kind('tooltip:AddLine(14, "Requires Level")', "ItemsTab.lua"), "tooltip")
        self.assertEqual(prep.site_kind('t_insert(breakdown, "Base damage")', "CalcOffence.lua"), "breakdown")
        self.assertEqual(prep.site_kind('new("ButtonControl", nil, {0, 0, 80, 20}, "Craft Item")', "ItemsTab.lua"), "control")
        self.assertEqual(prep.site_kind('{ var = "x", label = "Is the enemy Moving?" }', "ConfigOptions.lua"), "config")


if __name__ == "__main__":
    unittest.main()
