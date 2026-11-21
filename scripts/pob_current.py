#!/usr/bin/env python3
"""Locate the build PoB currently has open, or opened last.

PoB writes `<Mode mode="BUILD"><Arg string="<file>"/><Arg string="<name>"/>`
to Settings.xml only on exit or when options are saved. While it runs, the
window title is `<build name> (<class>) - Path of Building (PoE2)`, so a
running PoB window takes precedence over Settings.xml.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

TITLE = re.compile(r'^(?P<name>.+) \([^()]*\) - Path of Building')


def settings_entry(user_dir):
    """Return (build file, build name, builds dir) from Settings.xml."""
    root = ET.parse(Path(user_dir) / 'Settings.xml').getroot()
    builds = Path(user_dir) / 'Builds'
    misc = root.find('Misc')
    if misc is not None and misc.get('buildPath'):
        builds = Path(misc.get('buildPath'))
    mode = root.find('Mode')
    if mode is None or mode.get('mode') != 'BUILD':
        return None, None, builds
    args = [arg.get('string') for arg in mode.findall('Arg')]
    path = args[0] if args and args[0] else None
    name = args[1] if len(args) > 1 else None
    return path, name, builds


def remap(path, builds):
    """Map a stale absolute path (PoB folder moved) into the current builds dir."""
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    parts = re.split(r'[\\/]', path)
    lowered = [part.lower() for part in parts]
    if 'builds' in lowered:
        index = len(lowered) - 1 - lowered[::-1].index('builds')
        moved = Path(builds, *parts[index + 1:])
        if moved.is_file():
            return moved
    return None


def find_by_name(name, builds):
    matches = [p for p in Path(builds).rglob('*.xml') if p.stem == name]
    return max(matches, key=lambda p: p.stat().st_mtime_ns) if matches else None


def pob_windows():
    """Yield (title, exe path) for visible PoB windows (Windows only)."""
    if sys.platform != 'win32':
        return []
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length and user32.IsWindowVisible(hwnd):
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if 'Path of Building' in buffer.value:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                process = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
                exe = None
                if process:
                    path = ctypes.create_unicode_buffer(32768)
                    size = wintypes.DWORD(len(path))
                    if kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
                        exe = Path(path.value)
                    kernel32.CloseHandle(process)
                found.append((buffer.value, exe))
        return True

    user32.EnumWindows(visit, 0)
    return found


def documents_dir():
    if sys.platform == 'win32':
        import ctypes
        buffer = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:  # CSIDL_PERSONAL
            return Path(buffer.value)
    return Path.home() / 'Documents'


def user_dirs(exe):
    """PoB keeps data next to the scripts when portable, else in Documents."""
    if exe:
        for directory in (exe.parent, exe.parent.parent / 'src'):
            if (directory / 'Settings.xml').is_file():
                return [directory]
    return [documents_dir() / 'Path of Building (PoE2)']


def locate(user_dir=None, windows=None):
    """Return {'path', 'name', 'source'}; raise ValueError if nothing is found."""
    windows = pob_windows() if windows is None else windows
    open_names = []
    directories = [Path(user_dir)] if user_dir else []
    for title, exe in windows:
        match = TITLE.match(title)
        if match:
            open_names.append(match.group('name'))
        if not user_dir:
            directories += [d for d in user_dirs(exe) if d not in directories]
    if not directories:
        directories = user_dirs(None)
    for directory in directories:
        if not (directory / 'Settings.xml').is_file():
            continue
        path, name, builds = settings_entry(directory)
        saved = remap(path, builds) if path else None
        for open_name in open_names:
            if saved and saved.stem == open_name:
                return {'path': str(saved), 'name': open_name, 'source': 'window'}
            match = find_by_name(open_name, builds)
            if match:
                return {'path': str(match), 'name': open_name, 'source': 'window'}
        if saved:
            return {'path': str(saved), 'name': name, 'source': 'settings'}
    raise ValueError('未找到 PoB 当前或最近打开的 BD 文件（未保存的新 BD 没有文件）')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pob-user-dir', type=Path, help='含 Settings.xml 的 PoB 用户目录')
    args = parser.parse_args()
    try:
        result = locate(args.pob_user_dir)
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
