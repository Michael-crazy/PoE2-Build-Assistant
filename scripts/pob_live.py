#!/usr/bin/env python3
"""Find the build open in a running PoB, unsaved edits included (U02).

Our PoB branch (src/Modules/AssistantLiveBuild.lua) rewrites
<PoB user dir>/Assistant/live/<pid>.xml after every recalculation: line 1 is
`<!--poe2-assistant-live {json}-->` (protocol, pid, seq, revision, unsaved,
path, name), then the XML that saving would write, then
`<!--poe2-assistant-live-end <seq>-->`. Closing the build rewrites the file as
`{"closed": true}`. A snapshot counts only while its process is running and
started before the file was written (a reused pid started later).
"""
import json
import os
from pathlib import Path
import re
import sys
import time

from pob_current import documents_dir, pob_windows

PROTOCOL = 'pob-live/1'
LIVE_DIR = Path('Assistant/live')
HEADER = re.compile(r'<!--poe2-assistant-live (\{.*\})-->\r?\n')
TRAILER = re.compile(r'\r?\n<!--poe2-assistant-live-end (\d+)-->\r?\n?$')
START_SLACK = 2.0  # seconds: file and process clocks have different resolutions


def process_started(pid):
    """Start time (epoch seconds) of a running process, 0 if unknown, None if not running."""
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return 0 if ctypes.get_last_error() == 5 else None  # access denied: running
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return 0
            ticks = times[0].dwHighDateTime << 32 | times[0].dwLowDateTime
            return ticks / 1e7 - 11644473600  # FILETIME epoch is 1601
        finally:
            kernel32.CloseHandle(handle)
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        boot = next(float(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines()
                    if line.startswith('btime '))
        return boot + int(fields[19]) / os.sysconf('SC_CLK_TCK')
    except (OSError, IndexError, StopIteration, ValueError):
        return None


def live_dirs(user_dir=None, windows=None):
    """User dirs a PoB may write live snapshots to: the given one, those of open
    PoB windows (portable: next to the exe or ../src), and Documents."""
    windows = pob_windows() if windows is None else windows
    candidates = [Path(user_dir)] if user_dir else []
    for _, exe in windows:
        if exe:
            candidates += [exe.parent, exe.parent.parent / 'src']
    if not user_dir:
        candidates.append(documents_dir() / 'Path of Building (PoE2)')
    found = []
    for directory in candidates:
        if (directory / LIVE_DIR).is_dir() and directory not in found:
            found.append(directory)
    return found


def read_snapshot(path, attempts=5):
    """Parsed snapshot: meta with 'xml' (None when closed); None if not ours.
    A file PoB is rewriting has no matching end line yet; retry briefly."""
    for attempt in range(attempts):
        text = path.read_bytes().decode('utf-8', errors='replace')
        header = HEADER.match(text)
        if not header:
            return None
        meta = json.loads(header[1])
        if meta.get('protocol') != PROTOCOL:
            return None
        if meta.get('closed'):
            return {**meta, 'xml': None}
        trailer = TRAILER.search(text, header.end())
        if trailer and int(trailer[1]) == meta.get('seq'):
            return {**meta, 'xml': text[header.end():trailer.start()]}
        if attempt + 1 < attempts:
            time.sleep(0.05)
    raise ValueError('PoB 正在写入当前 BD，稍后再试')


def find(directories, started=process_started, include_closed=False):
    """Newest live snapshot of a running PoB, as {'file', 'pid', 'seq', 'mtime_ns', 'closed'}; None if none.
    A PoB showing its build list has a closed snapshot, counted only with include_closed."""
    best = None
    for directory in directories:
        for file in (Path(directory) / LIVE_DIR).glob('*.xml'):
            if not file.stem.isdigit():
                continue
            try:
                info = file.stat()
                begun = started(int(file.stem))
                if begun is None:
                    file.unlink()  # left behind by a PoB that exited without closing the build
                    continue
                if begun > info.st_mtime + START_SLACK:
                    continue  # pid reused by a later process
                with file.open('rb') as handle:
                    header = HEADER.match(handle.readline().decode('utf-8', errors='replace'))
            except OSError:
                continue
            if not header:
                continue
            meta = json.loads(header[1])
            if meta.get('protocol') != PROTOCOL or (meta.get('closed') and not include_closed):
                continue
            if best is None or info.st_mtime_ns > best['mtime_ns']:
                best = {'file': file, 'pid': int(file.stem), 'seq': meta.get('seq'), 'mtime_ns': info.st_mtime_ns,
                        'closed': bool(meta.get('closed'))}
    return best
