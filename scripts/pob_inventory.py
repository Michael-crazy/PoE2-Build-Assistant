"""Read-only engine inventory using the disposable P02 worker launcher."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

from pob_trial import PIN

STATES = {'equipped', 'empty', 'inactive_weapon_set', 'inactive_slot',
          'engine_removed', 'engine_excluded', 'stored_consumable'}


def inventory(build_path, worker, timeout=120):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be positive')
    data = Path(build_path).read_bytes()
    request = {'protocol': 'pob-inventory/1',
               'engine_commit': json.loads(PIN.read_text())['commit'],
               'build_xml': data.decode('utf-8')}
    payload = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    with tempfile.TemporaryDirectory(prefix='pob-inventory-') as directory:
        result = subprocess.run(worker, input=payload, capture_output=True,
                                cwd=directory, timeout=timeout, shell=False)
    if result.returncode:
        raise ValueError('PoB inventory worker failed: ' + result.stderr.decode(errors='replace')[-2000:])
    response = json.loads(result.stdout)
    expected = {'protocol': request['protocol'], 'engine_commit': request['engine_commit'],
                'request_sha256': hashlib.sha256(payload).hexdigest()}
    if not isinstance(response, dict) or any(response.get(k) != v for k, v in expected.items()):
        raise ValueError('inventory protocol, engine or input digest mismatch')
    if type(response.get('weapon_set')) is not int or response['weapon_set'] not in (1, 2):
        raise ValueError('invalid calculated weapon set')
    rows = response.get('inventory')
    if not isinstance(rows, list) or not rows:
        raise ValueError('missing engine inventory')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('slot'), str) or not row['slot'] or row['slot'] in seen:
            raise ValueError('invalid or duplicate inventory slot')
        seen.add(row['slot'])
        if row.get('state') not in STATES:
            raise ValueError('unknown inventory state')
        for key in ('stored_item_id', 'selected_item_id'):
            if not isinstance(row.get(key), str) or not row[key].isdecimal():
                raise ValueError('invalid inventory item ID')
        if row['state'] == 'equipped':
            if row.get('effective_item_id') != row['selected_item_id'] or row['selected_item_id'] == '0':
                raise ValueError('equipped inventory item mismatch')
        elif row.get('effective_item_id') is not None:
            raise ValueError('excluded inventory slot has effective item')
    return {**response, 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', required=True, type=Path)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('worker', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    worker = args.worker[1:] if args.worker[:1] == ['--'] else args.worker
    if not worker:
        parser.error('worker command required')
    try:
        result = inventory(args.build, worker, args.timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
