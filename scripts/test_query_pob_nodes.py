"""Authored two-version fixtures; no network, Lua execution or BD generation."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from query_pob_nodes import NodeLookup

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    def declaration(path, line):
        return dict(source_file=path, source_line=line)
    def node(identity, key, name, string_id, version):
        return dict(id=identity, source_key=key, name_en=name, string_id=string_id,
                    declaration=declaration(f'fixture/{version}.lua', key + 10))
    return dict(schema_version=1,
                source=dict(repository='authored-offline-fixture', branch='fixture', commit='1' * 40,
                            files=[dict(path='fixture/old.lua', sha256='2' * 64),
                                   dict(path='fixture/new.lua', sha256='3' * 64)]),
                default_tree_version='old', latest_tree_version='new', tree_versions=[
                    dict(tree_version='old', display='Old fixture', num=0.1,
                         declaration=declaration('fixture/versions.lua', 1), nodes=[
                             node(7, 70, 'Shared Name', None, 'old'),
                             node(8, 80, 'Shared Name', None, 'old')]),
                    dict(tree_version='new', display='New fixture', num=0.2,
                         declaration=declaration('fixture/versions.lua', 2), nodes=[
                             node(7, 90, 'Changed Name', 'NewSeven', 'new'),
                             node(9, 7, 'Shared Name', 'NewNine', 'new')])])


class NodeQueryTests(unittest.TestCase):
    def setUp(self):
        self.index = fixture()
        self.lookup = NodeLookup(self.index)

    def test_explicit_version_and_id_namespace(self):
        for version, name, key in [('old', 'Shared Name', 70), ('new', 'Changed Name', 90)]:
            result = self.lookup.query(version, 7)
            self.assertEqual((result['status'], result['candidate_count']), ('single_candidate', 1))
            self.assertEqual(result['query'], dict(tree_version=version, by='id', value=7))
            self.assertEqual(result['candidates'][0]['name_en'], name)
            self.assertEqual(result['candidates'][0]['source_key'], key)
        self.assertIsNone(self.lookup.query('old', 7)['candidates'][0]['string_id'])
        self.assertEqual(self.lookup.query('new', 7)['candidates'][0]['string_id'], 'NewSeven')
        self.assertEqual(self.lookup.query('old', 8)['candidate_count'], 1)  # Same names are legal.
        for version, identity in [('old', 9), ('new', 8), ('old', 70), ('new', 90), ('new', 0)]:
            result = self.lookup.query(version, identity)
            self.assertEqual((result['status'], result['candidate_count'], result['candidates']),
                             ('not_found', 0, []))
            self.assertEqual(result['source'], self.index['source'])
            self.assertEqual(result['tree_version']['tree_version'], version)

    def test_unknown_versions_and_invalid_ids(self):
        for version in (None, '', 'unknown', 'latest', 'default', [], 1):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'unknown tree version'):
                self.lookup.query(version, 7)
        for identity in (None, '7', True, False, -1, 7.0, [], 'Shared Name', 'NewSeven'):
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, 'node ID'):
                self.lookup.query('old', identity)
        with self.assertRaises(TypeError):
            self.lookup.query(node_id=7)

    def test_provenance_and_copy_isolation(self):
        expected = deepcopy(self.index)
        self.index['source']['files'][0]['sha256'] = 'changed'
        self.index['tree_versions'][0]['nodes'][0]['name_en'] = 'changed'
        result = self.lookup.query('old', 7)
        self.assertEqual(result['source'], expected['source'])
        self.assertEqual(result['tree_version'], {k: v for k, v in expected['tree_versions'][0].items() if k != 'nodes'})
        self.assertEqual(result['candidates'], [expected['tree_versions'][0]['nodes'][0]])
        result['source']['files'].clear()
        result['tree_version']['declaration']['source_line'] = 99
        result['candidates'][0]['declaration']['source_line'] = 99
        again = self.lookup.query('old', 7)
        self.assertEqual(again['source'], expected['source'])
        self.assertEqual(again['tree_version']['declaration']['source_line'], 1)
        self.assertEqual(again['candidates'][0]['declaration']['source_line'], 80)

    def test_reject_inconsistent_indices(self):
        for modify in (
                lambda i: i.update(schema_version=True),
                lambda i: i['source'].update(commit='invalid'),
                lambda i: i['tree_versions'].append(deepcopy(i['tree_versions'][0])),
                lambda i: i['tree_versions'][0].update(nodes={}),
                lambda i: i['tree_versions'][0]['nodes'][1].update(id=7),
                lambda i: i['tree_versions'][0]['nodes'][1].update(source_key=70),
                lambda i: i['tree_versions'][0]['nodes'][0].update(id=True),
                lambda i: i['tree_versions'][0]['nodes'][0].update(string_id=5),
                lambda i: i['tree_versions'][0]['nodes'][0].pop('string_id'),
                lambda i: i['tree_versions'][0]['nodes'][0].update(declaration={})):
            index = fixture()
            modify(index)
            with self.assertRaises(ValueError):
                NodeLookup(index)
        with self.assertRaisesRegex(ValueError, 'pinned manifest'):
            NodeLookup(fixture(), dict(repository='different', branch='fixture', commit='1' * 40))

    def test_cli_authored_fixture_and_errors(self):
        def run(*args):
            return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/query_pob_nodes.py'), *args],
                                  capture_output=True, text=True, timeout=5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nodes.json'
            index = fixture()
            # Borrow only pinned metadata to exercise the CLI manifest check; nodes remain authored.
            index['source'].update(json.loads((ROOT / 'sources/pob.json').read_text()))
            path.write_text(json.dumps(index))
            for version, identity, status in [('old', '7', 'single_candidate'), ('new', '8', 'not_found')]:
                result = run('--index', str(path), '--tree-version', version, identity)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output['status'], status)
                self.assertEqual(output['source'], index['source'])
            for version, identity in [('unknown', '7'), ('latest', '7'), ('old', '-1')]:
                result = run('--index', str(path), '--tree-version', version, identity)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)
            for content in ('{', '[]', json.dumps(fixture())):
                path.write_text(content)
                result = run('--index', str(path), '--tree-version', 'old', '7')
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)
            path.unlink()
            self.assertEqual(run('--index', str(path), '--tree-version', 'old', '7').returncode, 1)
        for args in [('7',), ('--tree-version', 'old'), ('--tree-version', 'old', 'Shared Name')]:
            self.assertEqual(run(*args).returncode, 2)


if __name__ == '__main__':
    unittest.main()
