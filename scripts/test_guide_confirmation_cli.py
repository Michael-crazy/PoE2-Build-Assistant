"""Offline CLI confirmation round trips using authored input and pinned indexes."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from guide_contract import validate_guide
from guide_confirmation import validate_confirmation

ROOT = Path(__file__).resolve().parents[1]


def confirmation_for(result):
    return dict(schema_version=1, context=deepcopy(result['confirmation_context']),
                selection=dict(main_skill_id='FireballPlayer', class_integer_id=6,
                               ascendancy=dict(class_integer_id=6, id='Titan'), passive_node_ids=[4]))


class GuideConfirmationCLITests(unittest.TestCase):
    def test_confirmation_rejection_requery_recovery_and_unchanged_files(self):
        data = json.loads((ROOT / 'tests/fixtures/a01/confirmation-guide.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide_path, confirmation_path = root / 'guide.json', root / 'confirmation.json'
            guide_path.write_text(json.dumps(data))

            def run(*extra):
                return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/guide_contract.py'),
                                       str(guide_path), *map(str, extra)], cwd=root,
                                      capture_output=True, text=True, timeout=5)

            query = run()
            self.assertEqual(query.returncode, 0, query.stderr)
            baseline = json.loads(query.stdout)
            self.assertEqual(baseline, validate_guide(data))
            self.assertNotIn('candidate_selection', baseline)
            confirmation = confirmation_for(baseline)

            def confirm(content, error=None):
                confirmation_path.write_text(content)
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                result = run('--confirmation', confirmation_path)
                self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
                if error:
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, '')
                    self.assertIn(error, result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = json.loads(result.stdout)
                    self.assertEqual(output, validate_confirmation(data, confirmation))
                    self.assertEqual(output.pop('candidate_selection'),
                                     dict(status='validated', input=confirmation))
                    self.assertEqual(output, baseline)
                return result

            confirm(json.dumps(confirmation))
            stale = deepcopy(confirmation)
            stale['context']['sources']['skills']['commit'] = '0' * 40
            confirm(json.dumps(stale), 'stale or mismatched')
            bad = deepcopy(confirmation)
            bad['selection']['passive_node_ids'] = [999999]
            confirm(json.dumps(bad), 'not in original candidates')
            for content, error in [('{', 'Expecting'), ('null', 'confirmation'), ('{}', 'confirmation')]:
                confirm(content, error)
            confirmation_path.unlink()
            missing = run('--confirmation', confirmation_path)
            self.assertEqual(missing.returncode, 1)
            self.assertEqual(missing.stdout, '')
            # A changed source invalidates the old selection even with unchanged IDs.
            data['source']['text'] += '\nAuthored revision.'
            guide_path.write_text(json.dumps(data))
            confirm(json.dumps(confirmation), 'stale or mismatched')
            query = run()
            self.assertEqual(query.returncode, 0, query.stderr)
            baseline = json.loads(query.stdout)
            confirmation = confirmation_for(baseline)
            confirm(json.dumps(confirmation))
            self.assertEqual(set(p.name for p in root.iterdir()), {'guide.json', 'confirmation.json'})


if __name__ == '__main__':
    unittest.main()
