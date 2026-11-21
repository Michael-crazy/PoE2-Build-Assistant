"""Authored fixtures only; no live sources, Lua runtime or BD generation."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from query_pob_classes import ClassLookup

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    def declaration(line):
        return dict(source_file='authored-fixture.lua', source_line=line)
    def asc(index, identity, internal, name):
        return dict(ascendancy_index=index, id=identity, internal_id=internal,
                    name_en=name, declaration=declaration(10 + index))
    classes = [dict(source_index=1, integer_id=7, name_en='Shared Class',
                    declaration=declaration(1), ascendancies=[
                        asc(1, 'Alpha', 'Fixture3', 'Shared'),
                        asc(3, 'Shared', 'Alpha', 'Alpha')]),
               dict(source_index=7, integer_id=2, name_en='Shared Class',
                    declaration=declaration(20), ascendancies=[
                        asc(1, 'Beta', 'Fixture1', 'Shared')])]
    old = dict(tree_version='old', display='Old fixture', num=0.1,
               declaration=declaration(30), classes=classes)
    new = deepcopy(old)
    new.update(tree_version='new', display='New fixture', num=0.2)
    new['classes'][0]['integer_id'] = 9
    new['classes'][0]['ascendancies'][0]['name_en'] = 'Changed'
    return dict(schema_version=1, source=dict(repository='authored-offline-fixture',
                branch='fixture', commit='1' * 40), default_tree_version='old',
                latest_tree_version='new', tree_versions=[old, new])


class ClassQueryTests(unittest.TestCase):
    def setUp(self):
        self.index = fixture()
        self.lookup = ClassLookup(self.index)

    def test_class_name_ambiguity_and_number_namespaces(self):
        result = self.lookup.query('old', 'class', 'name', 'Shared Class')
        self.assertEqual((result['status'], result['candidate_count']), ('ambiguous', 2))
        for by, expected in [('integer_id', 7), ('source_index', 2)]:
            result = self.lookup.query('old', 'class', by, 7)
            self.assertEqual(result['status'], 'single_candidate')
            self.assertEqual(result['candidates'][0]['class_identity']['integer_id'], expected)
        self.assertEqual(self.lookup.query('old', 'class', 'name', '7')['status'], 'not_found')

    def test_ascendancy_namespaces_do_not_infer_suffixes(self):
        for by, value, expected in [('name', 'Alpha', 'Shared'), ('id', 'Alpha', 'Alpha'),
                                     ('internal_id', 'Alpha', 'Shared'),
                                     ('ascendancy_index', 3, 'Shared')]:
            result = self.lookup.query('old', 'ascendancy', by, value, 7)
            self.assertEqual(result['status'], 'single_candidate')
            self.assertEqual(result['candidates'][0]['ascendancy']['id'], expected)
        self.assertEqual(self.lookup.query('old', 'ascendancy', 'id', 'Fixture3')['status'], 'not_found')

    def test_ownership_is_returned_and_filter_uses_integer_id(self):
        result = self.lookup.query('old', 'ascendancy', 'name', 'Shared')
        self.assertEqual(result['status'], 'ambiguous')
        self.assertEqual([r['class_identity']['integer_id'] for r in result['candidates']], [7, 2])
        for owner, expected in [(7, 'Alpha'), (2, 'Beta')]:
            result = self.lookup.query('old', 'ascendancy', 'ascendancy_index', 1, owner)
            self.assertEqual(result['candidates'][0]['ascendancy']['id'], expected)
        for owner in (1, 999):
            self.assertEqual(self.lookup.query('old', 'ascendancy', 'id', 'Alpha', owner)['status'], 'not_found')
        self.assertEqual(self.lookup.query('old', 'ascendancy', 'id', 'Alpha', 2)['status'], 'not_found')

    def test_versions_are_required_and_isolated(self):
        self.assertEqual(self.lookup.query('new', 'class', 'integer_id', 7)['status'], 'not_found')
        self.assertEqual(self.lookup.query('new', 'class', 'integer_id', 9)['status'], 'single_candidate')
        self.assertEqual(self.lookup.query('old', 'ascendancy', 'name', 'Changed')['status'], 'not_found')
        self.assertEqual(self.lookup.query('new', 'ascendancy', 'name', 'Shared')['candidate_count'], 1)
        for version in ('', 'unknown', 'latest', 'default', None):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'unknown tree version'):
                self.lookup.query(version, 'class', 'name', 'Shared Class')

    def test_exact_text_empty_and_unknown_queries(self):
        for value in ('', ' ', '\t'):
            self.assertEqual(self.lookup.query('old', 'class', 'name', value)['status'], 'empty_query')
        for value in ('shared class', ' Shared Class ', '中文职业', 'Unknown'):
            self.assertEqual(self.lookup.query('old', 'class', 'name', value)['status'], 'not_found')

    def test_provenance_and_mutation_isolation(self):
        self.index['tree_versions'][0]['classes'][0]['name_en'] = 'changed input'
        result = self.lookup.query('old', 'ascendancy', 'id', 'Alpha')
        self.assertEqual(result['source'], fixture()['source'])
        self.assertEqual(result['tree_version']['declaration']['source_line'], 30)
        self.assertEqual(result['candidates'][0]['ascendancy']['declaration']['source_line'], 11)
        result['candidates'][0]['class_identity']['integer_id'] = 99
        result['candidates'][0]['ascendancy']['id'] = 'mutated'
        result['source']['commit'] = 'changed'
        self.assertEqual(self.lookup.query('old', 'ascendancy', 'id', 'Alpha')['candidates'][0]
                         ['class_identity']['integer_id'], 7)
        self.assertEqual(self.lookup.source, fixture()['source'])

    def test_invalid_queries_and_inconsistent_indices(self):
        for kind, by, value, owner in [('class', 'id', 'Alpha', None),
                ('ascendancy', 'integer_id', 7, None), ('class', 'integer_id', '7', None),
                ('class', 'integer_id', True, None), ('ascendancy', 'name', 7, None),
                ('class', 'name', 'Shared Class', 7), ('ascendancy', 'id', 'Alpha', True)]:
            with self.subTest(by=by, value=value), self.assertRaises(ValueError):
                self.lookup.query('old', kind, by, value, owner)
        for modify in (lambda i: i.update(schema_version=True),
                       lambda i: i['source'].update(commit='invalid'),
                       lambda i: i['tree_versions'].append(deepcopy(i['tree_versions'][0])),
                       lambda i: i['tree_versions'][0]['classes'][1].update(integer_id=7),
                       lambda i: i['tree_versions'][0]['classes'][0]['ascendancies'][1].update(id='Alpha'),
                       lambda i: i['tree_versions'][0]['classes'][0].update(declaration={})):
            index = fixture()
            modify(index)
            with self.assertRaises(ValueError):
                ClassLookup(index)
        with self.assertRaisesRegex(ValueError, 'pinned manifest'):
            ClassLookup(fixture(), dict(fixture()['source'], commit='2' * 40))

    def test_cli_fixture_and_errors(self):
        def run(*args):
            return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/query_pob_classes.py'),
                                   *args], capture_output=True, text=True, timeout=5)
        args = ('--tree-version', 'old', '--kind', 'ascendancy', '--by', 'id', 'Alpha')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'index.json'
            index = fixture()
            # CLI requires the pinned source, even for authored data; this is not an upstream sample.
            index['source'] = json.loads((ROOT / 'sources/pob.json').read_text())
            path.write_text(json.dumps(index))
            result = run('--index', str(path), *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['candidates'][0]['ascendancy']['id'], 'Alpha')
            result = run('--index', str(path), '--tree-version', 'missing', '--kind', 'class', '--by', 'name', 'X')
            self.assertEqual(result.returncode, 1)
            self.assertIn('unknown tree version', result.stderr)
            for content in ('{', '[]', json.dumps(fixture())):
                path.write_text(content)
                result = run('--index', str(path), *args)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)
        result = run('--kind', 'class', '--by', 'name', 'X')
        self.assertEqual(result.returncode, 2)
        self.assertIn('--tree-version', result.stderr)


if __name__ == '__main__':
    unittest.main()
