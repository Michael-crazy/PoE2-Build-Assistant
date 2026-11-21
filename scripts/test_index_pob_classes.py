"""Authored data and temporary Git repositories, no live sources or Lua runtime."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from index_pob_classes import build_index, parse_classes, parse_versions

VERSIONS = '''treeVersionList = { "old", "new" }
latestTreeVersion = treeVersionList[#treeVersionList]
defaultTreeVersion = treeVersionList[1]
treeVersions = {
 ["old"] = { display = "Old fixture", num = 0.1, },
 ["new"] = { display = "New fixture", num = 0.2, },
}
'''
CLASSES = '''return {
\tclasses={
 [1]={
  ascendancies={
   [1]={ id="Shared", internalId="Fixture3", name="Shared Name", background={ name="Ignore } this", }, },
   [2]={ id="Other", internalId="Fixture1", name="Shared Name", },
  },
  integerId=7,
  name="Authored Class",
 },
 },
 nodes={ name="Not a class" },
}
'''


class ClassIndexTests(unittest.TestCase):
    def test_identity_names_and_locations(self):
        row, = parse_classes(CLASSES, 'fixture.lua')
        self.assertEqual((row['integer_id'], row['source_index'], row['name_en']), (7, 1, 'Authored Class'))
        self.assertEqual(row['declaration'], dict(source_file='fixture.lua', source_line=3))
        self.assertEqual([(a['ascendancy_index'], a['id'], a['internal_id'], a['name_en'], a['declaration']['source_line']) for a in row['ascendancies']],
                         [(1, 'Shared', 'Fixture3', 'Shared Name', 5), (2, 'Other', 'Fixture1', 'Shared Name', 6)])
        versions = parse_versions(VERSIONS)
        self.assertEqual([v['tree_version'] for v in versions], ['old', 'new'])
        self.assertEqual(versions[0]['declaration']['source_line'], 5)

    def test_unsupported_or_inconsistent_data_fails(self):
        for text in (CLASSES.replace('integerId=7', 'integerId="7"'),
                     CLASSES.replace('id="Other"', 'id="Other", id="Duplicate"'),
                     CLASSES.replace('internalId="Fixture1",', ''),
                     CLASSES.replace('name="Authored Class"', 'name="Escaped\\"name"'),
                     CLASSES.replace('\tclasses={', ' classes={')):
            with self.subTest(text=text), self.assertRaises((ValueError, KeyError)):
                parse_classes(text, 'fixture.lua')
        for text in (VERSIONS.replace('"old", "new"', '"old", "old"'),
                     VERSIONS.replace('["new"]', '["missing"]'),
                     VERSIONS.replace('treeVersionList[1]', '"old"')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_versions(text)

    def test_pinned_blobs_and_version_specific_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.check_output(['git', '-C', temp, *args]).decode().strip()
            git('init', '-q')
            (root / 'src').mkdir()
            (root / 'src/GameVersions.lua').write_text(VERSIONS)
            for version, identity in [('old', 7), ('new', 9)]:
                directory = root / f'src/TreeData/{version}'
                directory.mkdir(parents=True)
                (directory / 'tree.lua').write_text(CLASSES.replace('integerId=7', f'integerId={identity}'))
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'authored fixture')
            manifest = dict(repository='authored-offline-fixture', branch='fixture', commit=git('rev-parse', 'HEAD'))
            result = build_index(root, manifest)
            self.assertEqual(result['source']['commit'], manifest['commit'])
            self.assertEqual(len(result['source']['files']), 3)
            self.assertTrue(all(len(f['sha256']) == 64 for f in result['source']['files']))
            self.assertEqual([v['classes'][0]['integer_id'] for v in result['tree_versions']], [7, 9])
            self.assertEqual((result['default_tree_version'], result['latest_tree_version']), ('old', 'new'))
            (root / 'src/GameVersions.lua').write_text('uncommitted invalid')
            (root / 'src/TreeData/new/tree.lua').write_text('uncommitted invalid')
            (root / 'src/TreeData/untracked').mkdir()
            self.assertEqual(build_index(root, manifest), result)
            with self.assertRaisesRegex(ValueError, 'HEAD'):
                build_index(root, dict(manifest, commit='0' * 40))
            with self.assertRaisesRegex(ValueError, 'full commit'):
                build_index(root, dict(manifest, commit='short'))


if __name__ == '__main__':
    unittest.main()
