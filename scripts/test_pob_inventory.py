"""Inventory adapter boundary tests; real-engine cases are in tests/fixtures/m04/inventory."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pob_inventory import inventory


class InventoryTests(unittest.TestCase):
    def test_worker_contract_digest_and_slot_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory) / 'build.xml'
            build.write_text('<PathOfBuilding2/>')
            responses = []
            def worker(command, **kwargs):
                request = json.loads(kwargs['input'])
                self.assertEqual(request['protocol'], 'pob-inventory/1')
                self.assertNotIn('replacement', request)
                self.assertNotIn(str(build), kwargs['input'].decode())
                self.assertTrue(Path(kwargs['cwd']).is_dir())
                row = {'slot': 'Weapon 2', 'state': 'engine_removed', 'stored_item_id': '1',
                       'selected_item_id': '0', 'effective_item_id': None, 'effect_active': False}
                response = {key: request[key] for key in ('protocol', 'engine_commit')}
                response.update(request_sha256=hashlib.sha256(kwargs['input']).hexdigest(),
                                weapon_set=1, item_set_id='1', inventory=[row])
                if responses:
                    responses[0](response)
                return subprocess.CompletedProcess(command, 0, json.dumps(response).encode(), b'')
            with patch('pob_inventory.subprocess.run', side_effect=worker):
                result = inventory(build, ['worker'])
                self.assertEqual(result['sha256'], hashlib.sha256(build.read_bytes()).hexdigest())
                self.assertEqual(result['inventory'][0]['state'], 'engine_removed')
                for mutate in (
                    lambda r: r.update(request_sha256='stale'),
                    lambda r: r.update(engine_commit='other'),
                    lambda r: r['inventory'].append(deepcopy(r['inventory'][0])),
                    lambda r: r['inventory'][0].update(effective_item_id='1'),
                    lambda r: r['inventory'][0].update(state='equipped'),
                ):
                    responses[:] = [mutate]
                    with self.assertRaises(ValueError):
                        inventory(build, ['worker'])
            with patch('pob_inventory.subprocess.run', return_value=subprocess.CompletedProcess([], 1, b'', b'engine failure')):
                with self.assertRaisesRegex(ValueError, 'engine failure'):
                    inventory(build, ['worker'])


if __name__ == '__main__':
    unittest.main()
