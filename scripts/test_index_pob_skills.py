"""Authored Lua fixtures and local Git objects; no network or PoB runtime."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from index_pob_skills import build_index, parse_skills


class SkillIndexTests(unittest.TestCase):
    def test_names_preserve_ambiguity_empty_and_nested_fields(self):
        text = '''-- Authored fixture
skills["One"] = {
    name = "Shared Name",
    nested = { name = "Not a skill", },
}
skills["Two"] = {
    name = "Shared Name",
}
skills["Hidden"] = {
    name = "",
}
'''
        rows = parse_skills(text, 'fixture.lua')
        self.assertEqual([(r['id'], r['name_en'], r['source_line']) for r in rows],
                         [('One', 'Shared Name', 2), ('Two', 'Shared Name', 6), ('Hidden', '', 9)])

    def test_unknown_format_fails_instead_of_silently_dropping(self):
        for text in ('skills["One"] = {\n name = "Escaped\\\"name",\n}',
                     'skills["One"] = {\n label = "Missing name",\n}'):
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                parse_skills(text, 'fixture.lua')

    def test_pinned_blobs_reproducible_duplicates_preserved_conflicts_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def git(*args):
                return subprocess.check_output(['git', '-C', temp, *args]).decode().strip()

            git('init', '-q')
            directory = root / 'src/Data/Skills'
            directory.mkdir(parents=True)
            fixture = 'skills["One"] = {\n name = "Shared",\n}\n'
            (directory / 'act_int.lua').write_text(fixture)
            (directory / 'other.lua').write_text('skills["Two"] = {\n name = "Shared",\n}\n')
            (directory / 'SkillAssets.lua').write_text('return {}\n')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-qm', 'authored offline fixture')
            manifest = dict(repository='authored-local-fixture', branch='fixture', commit=git('rev-parse', 'HEAD'))
            index = build_index(root, manifest)
            self.assertEqual(index['summary'], dict(record_count=2, declaration_count=2, unnamed_count=0, ambiguous_name_count=1))
            self.assertEqual(len(index['source']['files']), 3)
            (directory / 'act_int.lua').write_text('uncommitted invalid Lua')
            (directory / 'untracked.lua').write_text(fixture)
            self.assertEqual(build_index(root, manifest), index)
            self.assertEqual(json.loads(json.dumps(index)), index)
            with self.assertRaisesRegex(ValueError, 'HEAD'):
                build_index(root, dict(manifest, commit='0' * 40))
            (directory / 'act_int.lua').write_text(fixture)
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-qm', 'duplicate fixture')
            duplicated = build_index(root, dict(manifest, commit=git('rev-parse', 'HEAD')))
            self.assertEqual(duplicated['summary']['declaration_count'], 3)
            self.assertEqual(len(duplicated['skills'][0]['declarations']), 2)
            (directory / 'untracked.lua').write_text(fixture.replace('Shared', 'Conflicting'))
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-qm', 'conflicting name fixture')
            with self.assertRaisesRegex(ValueError, 'conflicting names'):
                build_index(root, dict(manifest, commit=git('rev-parse', 'HEAD')))


if __name__ == '__main__':
    unittest.main()
