"""Authored P02 XML inventory and M04 assembly boundaries."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from build_slots import extract_build, selections_for_build, bind_selections
from slot_quotes import assemble_file
from build_estimate import aggregate_quotes

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'tests/fixtures/p02/real/build.xml'
ASSISTANT = ROOT / 'scripts/assistant.py'


class BuildSlotTests(unittest.TestCase):
    def test_p02_fixture_complete_empty_slots_and_original_unchanged(self):
        before = BUILD.read_bytes()
        build = extract_build(BUILD)
        self.assertEqual(build['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(build['weapon_set'], 1)
        self.assertEqual(len(build['inventory']), 17)
        selections = selections_for_build(build)
        self.assertEqual(len(selections), 15)
        self.assertEqual([r['slot'] for r in build['inventory'] if r['state'] == 'equipped'], ['Weapon 2'])
        self.assertIn('Hallowed Focus', build['inventory'][1]['build_item']['raw_text'])
        self.assertEqual(sum(r['state'] == 'empty' for r in build['inventory']), 14)
        self.assertEqual(BUILD.read_bytes(), before)
        for mutate in ('missing', 'duplicate', 'inactive', 'empty_quote'):
            rows = deepcopy(selections)
            if mutate == 'missing':
                rows.pop()
            elif mutate == 'duplicate':
                rows.append(rows[0])
            elif mutate == 'inactive':
                rows[0]['slot'] = 'Weapon 1 Swap'
            else:
                rows[0]['listing_id'] = 'authored-unique-001'
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                bind_selections(build, rows)

    def test_generated_manifest_to_assembly_both_realms_from_other_cwd(self):
        for realm, response in [('international', 'm01/listings.json'), ('tencent', 'm02/listings.synthetic.json')]:
            # Reuse existing manifests to avoid duplicating realm source configuration.
            source = ROOT / f'tests/fixtures/m04/{realm}.selections.synthetic.json'
            old = json.loads(source.read_text())
            with tempfile.TemporaryDirectory() as directory:
                generated = subprocess.run([sys.executable, '-B', str(ASSISTANT), 'build-selections',
                    '--build', str(BUILD), '--realm', realm, '--league', old['context']['league'],
                    '--response-file', str((source.parent / old['response_file']).resolve())],
                    capture_output=True, text=True, cwd='/tmp', timeout=5)
                self.assertEqual(generated.returncode, 0, generated.stderr)
                payload = json.loads(generated.stdout)
                path = Path(directory) / 'selection.json'
                path.write_text(json.dumps(payload))
                contract = assemble_file(path)
                output = aggregate_quotes(contract['slots'], **contract['context'])
                self.assertEqual(output['missing_slots'], [{'slot': 'Weapon 2', 'reason': 'missing_listing'}])
                self.assertEqual(output['quoted_slot_count'], 0)
                self.assertEqual(sum(r['status'] == 'empty_slot' for r in output['slots']), 14)
                # Explicit authored reference, no equipment compatibility claim.
                payload['selections'][1]['listing_id'] = old['selections'][0]['listing_id']
                path.write_text(json.dumps(payload))
                result = subprocess.run([sys.executable, '-B', str(ASSISTANT), 'estimate-build',
                    '--from-listings', str(path)], capture_output=True, text=True, cwd='/tmp', timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output['quoted_slot_count'], 1)
                self.assertEqual(output['slots'][1]['build_item']['id'], '1')
                self.assertEqual(output['build']['sha256'], extract_build(BUILD)['sha256'])
                payload['selections'][0]['listing_id'] = old['selections'][0]['listing_id']
                path.write_text(json.dumps(payload))
                result = subprocess.run([sys.executable, '-B', str(ASSISTANT), 'estimate-build',
                    '--from-listings', str(path)], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)

    def test_engine_inventory_drives_selections_and_estimate(self):
        rows = {'Weapon 2': ('equipped', '1'), 'Weapon 2 Swap': ('inactive_weapon_set', '1'),
                'Ring 1': ('empty', '0'), 'Ring 3': ('engine_excluded', '1'),
                'Arm 1': ('equipped', '1'), 'Flask 1': ('stored_consumable', '1')}
        inventory = [{'slot': slot, 'state': state, 'stored_item_id': item, 'selected_item_id': item,
                      'effective_item_id': item if state == 'equipped' else None}
                     for slot, (state, item) in rows.items()]
        stub = ('import hashlib, json, sys\n'
                'payload = sys.stdin.buffer.read(); request = json.loads(payload)\n'
                'print(json.dumps({"protocol": request["protocol"], "engine_commit": request["engine_commit"],\n'
                '    "request_sha256": hashlib.sha256(payload).hexdigest(), "weapon_set": 1, "item_set_id": "1",\n'
                f'    "inventory": json.loads({json.dumps(json.dumps(inventory))})}}))\n')
        source = ROOT / 'tests/fixtures/m04/international.selections.synthetic.json'
        listing = json.loads(source.read_text())['selections'][0]['listing_id']
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / 'worker.py'
            worker.write_text(stub)
            command = ['--', sys.executable, '-B', str(worker)]
            def run(*args):
                return subprocess.run([sys.executable, '-B', str(ASSISTANT), *args], capture_output=True,
                                      text=True, cwd='/tmp', timeout=10)
            generated = run('build-selections', '--build', str(BUILD), '--realm', 'international',
                            '--league', 'Offline Test League',
                            '--response-file', str(ROOT / 'tests/fixtures/m01/listings.json'), *command)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            payload = json.loads(generated.stdout)
            self.assertEqual(payload['build']['source'], 'engine')
            self.assertEqual([r['slot'] for r in payload['selections']], ['Weapon 2', 'Ring 1', 'Arm 1', 'Flask 1'])
            self.assertIn('Hallowed Focus', payload['build']['inventory'][4]['build_item']['raw_text'])
            for row in payload['selections']:
                if row['slot'] in ('Arm 1', 'Flask 1'):
                    row['listing_id'] = listing
            path = Path(directory) / 'selection.json'
            path.write_text(json.dumps(payload))
            result = run('estimate-build', '--from-listings', str(path), *command)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual({r['slot']: r['status'] for r in output['slots']},
                             {'Weapon 2': 'missing_listing', 'Ring 1': 'empty_slot',
                              'Arm 1': 'quoted', 'Flask 1': 'quoted'})
            self.assertEqual(output['missing_slots'], [{'slot': 'Weapon 2', 'reason': 'missing_listing'}])
            result = run('estimate-build', '--from-listings', str(path))
            self.assertEqual(result.returncode, 1)
            self.assertIn('worker', result.stderr)
            payload['selections'].append({'slot': 'Ring 3', 'listing_id': None, 'matched_affixes': []})
            path.write_text(json.dumps(payload))
            result = run('estimate-build', '--from-listings', str(path), *command)
            self.assertEqual(result.returncode, 1)

    def test_item_sets_and_main_skill_override_displayed_weapon_set(self):
        root = ET.fromstring(BUILD.read_bytes())
        items = root.find('Items')
        active = items.find('ItemSet')
        other = deepcopy(active)
        other.set('id', '2')
        items.append(other)
        items.set('activeItemSet', '2')
        other.set('useSecondWeaponSet', 'true')
        other.find("Slot[@name='Weapon 2 Swap']").set('itemId', '1')
        skill = root.find('./Skills/SkillSet/Skill')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'build.xml'
            for first, second, expected in [('true', 'true', 2), ('true', 'false', 1), ('false', 'true', 2)]:
                skill.set('set1', first)
                skill.set('set2', second)
                path.write_bytes(ET.tostring(root))
                result = extract_build(path)
                self.assertEqual(result['item_set_id'], '2')
                self.assertEqual(result['weapon_set'], expected)
                rows = selections_for_build(result)
                self.assertIn('Weapon 2 Swap' if expected == 2 else 'Weapon 2', [r['slot'] for r in rows])
                self.assertNotIn('Weapon 2' if expected == 2 else 'Weapon 2 Swap', [r['slot'] for r in rows])

    def test_malformed_missing_reference_and_conditional_equipment_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'build.xml'
            for case in ('xml', 'wrong_root', 'item_set', 'skill_set', 'main', 'dangling', 'duplicate', 'conditional', 'dynamic', 'rune'):
                root = ET.fromstring(BUILD.read_bytes())
                items = root.find('Items')
                active = items.find('ItemSet')
                if case == 'wrong_root': root.tag = 'PathOfBuilding'
                elif case == 'item_set': items.set('activeItemSet', '8')
                elif case == 'skill_set': root.find('Skills').set('activeSkillSet', '8')
                elif case == 'main': root.find('Build').set('mainSocketGroup', '99')
                elif case == 'dangling': active.find("Slot[@name='Weapon 2']").set('itemId', '99')
                elif case == 'duplicate': active.append(deepcopy(active.find('Slot')))
                elif case == 'conditional': active.find("Slot[@name='Ring 3']").set('itemId', '1')
                elif case == 'dynamic': ET.SubElement(active, 'Slot', name='Jewel 999', itemId='1')
                elif case == 'rune': active.find('RuneSlot').set('runeName', 'Authored rune')
                path.write_bytes(b'<' if case == 'xml' else ET.tostring(root))
                with self.subTest(case=case), self.assertRaises(ValueError): extract_build(path)


if __name__ == '__main__':
    unittest.main()
