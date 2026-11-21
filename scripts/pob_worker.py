#!/usr/bin/env python3
"""Launch the pinned Lua worker inside the trial adapter's disposable cwd."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def prepare(engine, destination):
    engine = Path(engine).resolve()
    pin = json.loads((ROOT / 'sources/pob.json').read_text())['commit']
    head = subprocess.check_output(['git', '-C', str(engine), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(engine), 'status', '--porcelain'], text=True)
    if head != pin or dirty:
        raise ValueError('worker requires a clean checkout at ' + pin)
    for name in ('src', 'runtime'):
        shutil.copytree(engine / name, destination / name, symlinks=False)
    shutil.copy2(engine / 'manifest.xml', destination / 'manifest.xml')
    if (destination / 'src/first.run').exists():
        raise ValueError('first.run installation is unsupported')
    return pin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--luajit', required=True, type=Path)
    args = parser.parse_args()
    executable = args.luajit.resolve(strict=True)
    # The parent adapter removes this directory, including any PoB settings/cache.
    destination = Path(tempfile.mkdtemp(prefix='engine-', dir=Path.cwd()))
    try:
        pin = prepare(args.engine, destination)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
    environment = dict(os.environ, POB_ENGINE_COMMIT=pin)
    environment.pop('CI', None)
    environment['LUA_PATH'] = '../runtime/lua/?.lua;../runtime/lua/?/init.lua;;'
    os.chdir(destination / 'src')
    os.execve(executable, [str(executable), str(ROOT / 'scripts/pob_worker.lua')], environment)


if __name__ == '__main__':
    main()
