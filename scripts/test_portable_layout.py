"""R02 synthetic layout regression only; no production updater or PoB launch."""

from pathlib import Path, PurePosixPath
import tempfile
import unittest
from zipfile import BadZipFile, ZipFile


def snapshot(directory):
    """Compare complete relative file sets and bytes, including unknown files."""
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in directory.rglob('*') if p.is_file()}


class PortableLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='r02 便携 测试 ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.install = self.root / 'portable'
        self.program = self.install / 'program'
        self.user = self.install / 'user'
        self.previous = self.install / 'previous-program'
        self.stage = self.install / 'staged-program'
        self.v1 = {'version.txt': b'synthetic-v1', 'bin/assistant.exe': b'fake-v1',
                   'pob/data.txt': b'fake-engine-v1', 'obsolete.txt': b'v1-only'}
        self.v2 = {'version.txt': b'synthetic-v2', 'bin/assistant.exe': b'fake-v2',
                   'pob/data.txt': b'fake-engine-v2', 'new.txt': b'v2-only'}
        self.write_files(self.program, self.v1)
        self.write_files(self.user, {
            'builds/开荒 BD.xml': '<synthetic>自编 BD，不是可加载 PoB</synthetic>'.encode(),
            'builds/终局.build': b'authored-build-placeholder\x00\xff',
            'settings/assistant.json': '{"language":"简体中文","realm":"tencent"}'.encode(),
            'settings/pob.xml': b'<SyntheticSettings version="1"/>',
            'unknown/custom.bin': bytes(range(256)),
        })
        self.original_user = snapshot(self.user)
        self.v2_zip = self.make_zip('v2.zip', self.v2)

    @staticmethod
    def write_files(directory, files):
        for name, content in files.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def make_zip(self, name, files):
        archive = self.root / name
        with ZipFile(archive, 'w') as output:
            for relative, content in files.items():
                output.writestr('program/' + relative, content)
        return archive

    def stage_synthetic_zip(self, archive):
        """Test-only staging model. Accept only the proposed program ZIP root."""
        with ZipFile(archive) as package:
            members = package.infolist()
            for member in members:
                path = PurePosixPath(member.filename)
                if (path.is_absolute() or '..' in path.parts
                        or '\\' in member.filename or ':' in member.filename
                        or not path.parts or path.parts[0] != 'program'
                        or len(path.parts) < 2):
                    raise ValueError('ZIP must contain only program/ files')
            # Read all bytes before staging; malformed input leaves installed dirs alone.
            files = {str(PurePosixPath(m.filename).relative_to('program')): package.read(m)
                     for m in members if not m.is_dir()}
        self.write_files(self.stage, files)

    def replace_synthetic_program(self):
        # Closed-process, same-filesystem model, without crash/lock guarantees.
        self.program.rename(self.previous)
        self.stage.rename(self.program)

    def rollback_synthetic_program(self):
        self.program.rename(self.install / 'rejected-program')
        self.previous.rename(self.program)

    def test_zip_replacement_and_rollback_preserve_all_user_bytes(self):
        self.assertEqual(snapshot(self.program), self.v1)
        self.stage_synthetic_zip(self.v2_zip)
        self.assertEqual(snapshot(self.program), self.v1)
        self.assertEqual(snapshot(self.user), self.original_user)
        self.replace_synthetic_program()
        self.assertEqual(snapshot(self.program), self.v2)  # obsolete file gone
        self.assertEqual(snapshot(self.previous), self.v1)
        self.assertEqual(snapshot(self.user), self.original_user)
        self.rollback_synthetic_program()
        self.assertEqual(snapshot(self.program), self.v1)  # v2-only file gone
        self.assertEqual(snapshot(self.install / 'rejected-program'), self.v2)
        self.assertEqual(snapshot(self.user), self.original_user)

    def test_rollback_keeps_builds_and_settings_saved_after_upgrade(self):
        self.stage_synthetic_zip(self.v2_zip)
        self.replace_synthetic_program()
        changes = {'builds/升级后新增 BD.xml': b'authored-new-build',
                   'builds/开荒 BD.xml': b'authored-edited-build',
                   'settings/assistant.json': b'{"language":"en","realm":"international"}'}
        self.write_files(self.user, changes)
        expected = self.original_user | changes
        self.assertEqual(snapshot(self.user), expected)
        self.rollback_synthetic_program()
        self.assertEqual(snapshot(self.program), self.v1)
        self.assertEqual(snapshot(self.user), expected)

    def test_invalid_zip_does_not_touch_program_or_user(self):
        archive = self.root / 'broken.zip'
        archive.write_bytes(b'not a zip')
        with self.assertRaises(BadZipFile):
            self.stage_synthetic_zip(archive)
        self.assertEqual(snapshot(self.program), self.v1)
        self.assertEqual(snapshot(self.user), self.original_user)
        self.assertFalse(self.stage.exists())
        self.assertFalse(self.previous.exists())

    def test_zip_user_payload_or_escape_is_rejected_before_staging(self):
        for name in ('user/settings/assistant.json', 'program/../user/settings/assistant.json',
                     '/user/escape', 'program/..\\user\\escape', 'program/C:/escape'):
            with self.subTest(member=name):
                archive = self.make_zip('wrong-layout.zip', self.v2)
                with ZipFile(archive, 'a') as package:
                    package.writestr(name, b'must not be written')
                with self.assertRaises(ValueError):
                    self.stage_synthetic_zip(archive)
                self.assertFalse(self.stage.exists())
                self.assertEqual(snapshot(self.program), self.v1)
                self.assertEqual(snapshot(self.user), self.original_user)


if __name__ == '__main__':
    unittest.main()
