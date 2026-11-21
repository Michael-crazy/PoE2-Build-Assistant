"""Authored Lua/term fixtures only; no network, PoB runtime or upstream data."""
import json
from pathlib import Path
import tempfile
import unittest

from index_pob_gems import assemble, join_terms, parse_effects, parse_gems

EFFECTS = '''-- Authored fixture
return function(skills, mod, flag, skill)
skills["BoltPlayer"] = {
\tname = "Bolt",
\tlevels = {
\t\t[1] = { levelRequirement = 0, },
\t\t[3] = { 4, levelRequirement = 7, },
\t},
\tstatSets = {
\t\t[1] = {
\t\t\tlevels = {
\t\t\t\t[1] = { levelRequirement = 99, },
\t\t\t},
\t\t},
\t},
}
\t\t\tskills["TriggeredBoltPlayer"] = {
\t\t\t\tname = "Bolt Echo",
\t\t\t\thideFromSideBar = true,
\t\t\t\tlevels = {
\t\t\t\t\t[1] = { baseMultiplier = 1, levelRequirement = 1 }
\t\t\t\t},
\t\t\t\tpreDamageFunc = function(activeSkill, output)
\t\t\t\t\toutput.x = 1
\t\t\t\tend,
\t\t\t}
skills["SupportBoltPlayer"] = {
\tname = "Bolt Support",
\tsupport = true,
\tlevels = {
\t\t[1] = { levelRequirement = 0, },
\t},
}
'''

GEMS = '''return {
\t["Gems/Bolt"] = {
\t\tname = "Bolt",
\t\tgameId = "Gem/Bolt",
\t\tvariantId = "Bolt",
\t\tgrantedEffectId = "BoltPlayer",
\t\tadditionalGrantedEffectId1 = "TriggeredBoltPlayer",
\t\tadditionalGrantedEffectId2 = "MissingPlayer",
\t\tadditionalStatSet1 = "BoltPlayerSecond",
\t\tnaturalMaxLevel = 20,
\t},
\t["Gems/BoltSupport"] = {
\t\tname = "Old",
\t\tgameId = "Gem/BoltSupport",
\t\tvariantId = "Old",
\t\tgrantedEffectId = "SupportBoltPlayer",
\t\tnaturalMaxLevel = 1,
\t},
\t["Gems/BoltSupport"] = {
\t\tname = "Bolt Support",
\t\tgameId = "Gem/BoltSupport",
\t\tvariantId = "BoltSupport",
\t\tgrantedEffectId = "SupportBoltPlayer",
\t\tnaturalMaxLevel = 1,
\t},
}
'''


def build():
    return assemble(parse_gems(GEMS), parse_effects(EFFECTS, 'fixture.lua'))


class GemIndexTests(unittest.TestCase):
    def test_effects_include_hand_written_declarations_and_exact_level_keys(self):
        rows = {r['id']: r for r in parse_effects(EFFECTS, 'fixture.lua')}
        self.assertEqual(list(rows), ['BoltPlayer', 'TriggeredBoltPlayer', 'SupportBoltPlayer'])
        bolt = rows['BoltPlayer']
        self.assertEqual((bolt['levels'], bolt['level_requirements']), ([1, 3], [0, 7]))
        echo = rows['TriggeredBoltPlayer']
        self.assertEqual((echo['name_en'], echo['hideFromSideBar'], echo['levels'], echo['level_requirements']),
                         ('Bolt Echo', True, [1], [1]))
        self.assertEqual(echo['declarations'][0]['source_line'], 17)
        self.assertTrue(rows['SupportBoltPlayer']['support'])

    def test_unknown_declaration_format_fails(self):
        for text in ('skills["X"] = { name = "X", levels = {} }\n',
                     'skills["X"] = {\n\tname = "X",\n\tlevels = {\n\t\t[1] = { actorLevel = 1, },\n\t},\n}\n'):
            with self.assertRaises(ValueError):
                parse_effects(text, 'fixture.lua')

    def test_identity_last_duplicate_wins_and_eligibility(self):
        gems, effects = build()
        bolt, support = gems
        self.assertEqual((bolt['gameId'], bolt['variantId'], bolt['grantedEffectId']),
                         ('Gem/Bolt', 'Bolt', 'BoltPlayer'))
        self.assertEqual(bolt['initializedGrantedEffectIds'], ['BoltPlayer', 'TriggeredBoltPlayer'])
        self.assertEqual(bolt['unresolvedAdditionalGrantedEffectIds'], ['MissingPlayer'])
        self.assertEqual(bolt['additionalStatSets'], {'additionalStatSet1': 'BoltPlayerSecond'})
        self.assertTrue(bolt['primary_player_skill_eligible'])
        self.assertFalse(bolt['natural_max_level_in_effect_levels'])
        self.assertEqual((support['variantId'], len(support['declarations'])), ('BoltSupport', 2))
        self.assertEqual(support['ineligible_reasons'], ['support'])
        by_id = {e['id']: e for e in effects}
        self.assertEqual(by_id['TriggeredBoltPlayer']['ineligible_reasons'], ['hideFromSideBar', 'no_primary_gem'])

    def test_terms_join_requires_full_identity_and_consistent_names(self):
        gems, _ = build()

        def terms(entries):
            temp = tempfile.TemporaryDirectory()
            self.addCleanup(temp.cleanup)
            for name in ('skill_gems', 'spirit_gems', 'meta_skill_gem', 'support_gems', 'lineage_supports'):
                gems_json = entries.get(name, {})
                Path(temp.name, f'{name}.json').write_text(
                    json.dumps(dict(metadata=dict(version='fixture'), gems=gems_json)), encoding='utf-8')
            return Path(temp.name)

        pob = dict(gameId='Gem/Bolt', variantId='Bolt', grantedEffectId='BoltPlayer')
        entry = dict(en='Bolt', zh_hans='简', zh_hant='繁', pob=pob)
        stale = dict(entry, pob=dict(pob, grantedEffectId='OtherPlayer'))
        result = join_terms(gems, terms(dict(skill_gems=dict(Bolt=entry, Stale=stale, NoPob=dict(entry, pob=None)),
                                             spirit_gems=dict(Bolt=entry))))
        self.assertEqual(gems[0]['names'], dict(zh_hans='简', zh_hant='繁'))
        self.assertEqual([r['file'] for r in gems[0]['term_refs']], ['skill_gems.json', 'spirit_gems.json'])
        self.assertIsNone(gems[1]['names'])
        self.assertEqual([u['slug'] for u in result['unjoined']], ['Stale'])
        gems, _ = build()
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            join_terms(gems, terms(dict(skill_gems=dict(Bolt=entry), spirit_gems=dict(Bolt=dict(entry, zh_hans='别')))))


if __name__ == '__main__':
    unittest.main()
