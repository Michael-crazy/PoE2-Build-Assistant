"""Authored Lua fixtures; no network, client or Lua execution."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from index_pob_nodes import build_index, parse_nodes
from test_index_pob_classes import VERSIONS

NODES = '''return {
 groups={ [1]={ nodes={ [1]=999, }, }, },
\tnodes={
 [900]={ skill=7, name="Shared Name", stringId="FixtureSeven",
  stats={ [1]="Ignore } skill=999", },
  flavourText="A \\"quote\\" and\\nline", },
 [901]={ skill=8, name="Shared Name", stringId="FixtureEight", },
 },
}
'''


class NodeIndexTests(unittest.TestCase):
    def test_identity_and_declaration(self):
        rows = parse_nodes(NODES, 'authored.lua')
        self.assertEqual([r['id'] for r in rows], [7, 8])
        self.assertEqual([r['source_key'] for r in rows], [900, 901])
        self.assertEqual([r['name_en'] for r in rows], ['Shared Name'] * 2)
        self.assertEqual(rows[0]['string_id'], 'FixtureSeven')
        self.assertEqual([r['declaration'] for r in rows], [
            dict(source_file='authored.lua', source_line=n) for n in (4, 7)])

    def test_older_nodes_without_string_id(self):
        row = parse_nodes(NODES.replace('stringId="FixtureSeven",', ''), 'old.lua')[0]
        self.assertIsNone(row['string_id'])

    def test_duplicates_and_bad_identities_fail(self):
        cases = [NODES.replace('skill=8', 'skill=7'),
                 NODES.replace('[901]', '[900]'),
                 NODES.replace('skill=7', 'skill=7, skill=9'),
                 NODES.replace('skill=7', 'skill="7"'),
                 NODES.replace('skill=7', 'skill=true'),
                 NODES.replace('skill=7', 'skill=-1'),
                 NODES.replace('skill=7', 'skill=7.5'),
                 NODES.replace('skill=7,', ''),
                 NODES.replace('stringId="FixtureSeven"', 'stringId=42'),
                 NODES.replace('name="Shared Name"', 'name=42'),
                 NODES.replace('\\nline', '\\tline'),
                 NODES.replace('\tnodes={', ' nodes={')]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_nodes(text, 'authored.lua')
        with self.assertRaisesRegex(ValueError, 'empty nodes'):
            parse_nodes('return {\n\tnodes={}\n}', 'empty.lua')
        with self.assertRaisesRegex(ValueError, 'one top-level'):
            parse_nodes(NODES + NODES, 'duplicate-table.lua')

    def test_pinned_blobs_version_isolation_and_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.check_output(['git', '-C', temp, *args]).decode().strip()
            git('init', '-q')
            (root / 'src').mkdir()
            (root / 'src/GameVersions.lua').write_text(VERSIONS)
            texts = {}
            for version, text in [('old', NODES), ('new', NODES.replace('FixtureSeven', 'NewSeven').replace('skill=8', 'skill=9'))]:
                path = f'src/TreeData/{version}/tree.lua'
                (root / path).parent.mkdir(parents=True)
                (root / path).write_text(text)
                texts[path] = text
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'authored nodes')
            manifest = dict(repository='authored-offline', branch='fixture', commit=git('rev-parse', 'HEAD'))
            result = build_index(root, manifest)
            old, new = result['tree_versions']
            self.assertEqual([r['id'] for r in old['nodes']], [7, 8])
            self.assertEqual([r['id'] for r in new['nodes']], [7, 9])
            self.assertEqual(new['nodes'][0]['string_id'], 'NewSeven')
            self.assertEqual(result['source']['commit'], manifest['commit'])
            self.assertEqual([r['tree_version'] for r in result['tree_versions']], ['old', 'new'])
            self.assertEqual((result['default_tree_version'], result['latest_tree_version']), ('old', 'new'))
            for source in result['source']['files']:
                self.assertEqual(source['sha256'], hashlib.sha256((root / source['path']).read_bytes()).hexdigest())
            for version in (old, new):
                for row in version['nodes']:
                    location = row['declaration']
                    self.assertTrue(texts[location['source_file']].splitlines()[location['source_line'] - 1].lstrip().startswith(f"[{row['source_key']}]={{"))
            (root / 'src/TreeData/new/tree.lua').write_text('uncommitted invalid')
            (root / 'src/GameVersions.lua').write_text('uncommitted invalid')
            (root / 'src/TreeData/extra').mkdir()
            self.assertEqual(build_index(root, manifest), result)
            with self.assertRaisesRegex(ValueError, 'HEAD'):
                build_index(root, dict(manifest, commit='0' * 40))
            with self.assertRaisesRegex(ValueError, 'full commit'):
                build_index(root, dict(manifest, commit='short'))


if __name__ == '__main__':
    unittest.main()
