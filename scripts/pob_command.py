#!/usr/bin/env python3
"""Send a command to the running PoB and read its result (U06).

The reverse of the U02 live snapshot. Next to <PoB user dir>/Assistant/live,
our PoB branch (src/Modules/AssistantCommands.lua) polls
Assistant/commands/<pid>.json about 4 times a second, also in the background.
We write `{"protocol": "pob-command/1", "seq": N, "command": ..., ...}` (whole,
by rename); PoB deletes it, runs it and writes <pid>.result.json with the same
seq and a `status`; it stays until the next result replaces it. Each command's
seq is one more than the last seen in either file, so a result left from an
earlier command is never taken for this one.
"""
import json
import os
from pathlib import Path
import time

import pob_live

PROTOCOL = 'pob-command/1'
COMMAND_DIR = Path('Assistant/commands')
TIMEOUT = 5.0  # PoB polls every 0.25 s; a recalculation may hold a frame longer
GRACE = 5.0  # after PoB took the command, wait this much longer for its result
POLL = 0.05


class CommandError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def find_pob(user_dir=None, started=pob_live.process_started):
    """The running PoB with an open build: its live snapshot ({'file', 'pid', ...})."""
    snapshot = pob_live.find(pob_live.live_dirs(user_dir), started=started, include_closed=True)
    if snapshot is None:
        raise CommandError('pob-not-running', 'PoB 未运行，无法加入')
    if snapshot['closed']:
        raise CommandError('pob-no-build', 'PoB 没有打开 BD，无法加入')
    return snapshot


def _seq(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8')).get('seq')
    except (OSError, ValueError, AttributeError):
        return 0
    return value if isinstance(value, int) else 0


def _write(path, data):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


def _result(path, seq):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None  # not there yet, or PoB is renaming it into place
    return data if isinstance(data, dict) and data.get('seq') == seq else None


def send(snapshot, command, started=pob_live.process_started, timeout=TIMEOUT, grace=GRACE):
    """Write one command for the PoB of `snapshot` and return its result dict."""
    pid = snapshot['pid']
    directory = snapshot['file'].parent.parent / COMMAND_DIR.name
    directory.mkdir(exist_ok=True)
    request, answer = directory / f'{pid}.json', directory / f'{pid}.result.json'
    seq = max(_seq(request), _seq(answer)) + 1
    _write(request, {'protocol': PROTOCOL, 'seq': seq, **command})
    deadline, taken = time.monotonic() + timeout, False
    while True:
        result = _result(answer, seq)
        if result is not None:
            return result  # the file stays: the next command's seq follows it
        if started(pid) is None:
            request.unlink(missing_ok=True)
            raise CommandError('pob-not-running', 'PoB 未运行，无法加入')
        if time.monotonic() > deadline:
            if taken:
                raise CommandError('pob-timeout', 'PoB 收到了命令但没有返回结果，请在 PoB 里查看是否已加入')
            try:
                request.unlink()  # withdraw it, so it is not added later by surprise
            except FileNotFoundError:  # PoB took it just now: its result follows
                deadline, taken = time.monotonic() + grace, True
            else:
                raise CommandError('pob-timeout', 'PoB 没有响应（可能正忙），未加入，请稍后再试')
        time.sleep(POLL)
