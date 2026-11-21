#!/usr/bin/env python3
"""Resident PoB trial server: load the engine once, answer JSON lines on stdio.

LuaJIT is loaded in-process through ctypes (PoB's own lua51.dll on Windows,
libluajit.so on Linux), so no separate interpreter is needed. The process
changes its cwd to the engine's src directory; pass absolute paths.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from pob_current import locate
import pob_live

ROOT = Path(__file__).resolve().parents[1]
PIN = json.loads((ROOT / 'sources/pob.json').read_text(encoding='utf-8'))['commit']
_BRANCH = ROOT / 'sources/pob-branch.json'  # absent in packages built before U04
BRANCH_HEAD = json.loads(_BRANCH.read_text(encoding='utf-8'))['head'] if _BRANCH.exists() else None
# The pinned base, our patch branch head on top of it (U04), and a candidate
# that ops/rebase_check.py names explicitly for a rebased scratch tree.
ACCEPTED = {PIN, BRANCH_HEAD, os.environ.get('POE2_POB_CANDIDATE')} - {None, ''}
SERVER_LUA = Path(__file__).with_name('pob_server.lua').resolve()
LINUX_RUNTIME = Path.home() / '.local/state/poe2-assistant/p02-runtime'
LUA_GLOBALSINDEX = -10002


def verify_engine(engine):
    """Require the pinned commit: a clean checkout or an export marked by .pob-commit."""
    if (engine / '.git').exists():
        head = subprocess.check_output(['git', '-C', str(engine), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(engine), 'status', '--porcelain'], text=True)
        if head not in ACCEPTED or dirty:
            raise ValueError(f'引擎必须是干净的固定提交 {PIN}')
    elif (engine / '.pob-commit').read_text(encoding='utf-8').strip() not in ACCEPTED:
        raise ValueError(f'引擎导出标记不是固定提交 {PIN}')


def engine_layout(engine):
    """(scripts directory, runtime directory): src/ and runtime/ in a repository checkout or
    export, or both the engine root in the official release layout (R02 package: PoB/)."""
    if (engine / 'src/Launch.lua').is_file():
        return engine / 'src', engine / 'runtime'
    return engine, engine


def default_runtime(engine):
    if sys.platform == 'win32':
        runtime = engine_layout(engine)[1]
        return runtime / 'lua51.dll', str(runtime / '?.dll')
    return LINUX_RUNTIME / 'LuaJIT/src/libluajit.so', str(LINUX_RUNTIME / '?.so')


class LuaEngine:
    """One LuaJIT state running HeadlessWrapper and pob_server.lua."""

    def __init__(self, engine, lua_lib=None, cpath=None):
        engine = Path(engine).resolve(strict=True)
        verify_engine(engine)
        default_lib, default_cpath = default_runtime(engine)
        lua_lib = Path(lua_lib or default_lib).resolve(strict=True)
        if sys.platform == 'win32':
            os.add_dll_directory(str(lua_lib.parent))
        # RTLD_GLOBAL lets C modules such as lua-utf8.so resolve lua_* symbols.
        lua = self.lua = ctypes.CDLL(str(lua_lib), mode=ctypes.RTLD_GLOBAL)
        p, i, s = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p
        lua.luaL_newstate.restype = p
        lua.luaL_openlibs.argtypes = [p]
        lua.luaL_loadbuffer.argtypes = [p, s, ctypes.c_size_t, s]
        lua.lua_pcall.argtypes = [p, i, i, i]
        lua.lua_getfield.argtypes = [p, i, s]
        lua.lua_setfield.argtypes = [p, i, s]
        lua.lua_pushlstring.argtypes = [p, s, ctypes.c_size_t]
        lua.lua_tolstring.argtypes = [p, i, ctypes.POINTER(ctypes.c_size_t)]
        lua.lua_tolstring.restype = ctypes.c_void_p
        lua.lua_settop.argtypes = [p, i]
        self.state = lua.luaL_newstate()
        lua.luaL_openlibs(self.state)
        scripts, runtime = engine_layout(engine)
        os.chdir(scripts)
        # Relative: LuaJIT opens files in the ANSI code page and the package path may be Chinese.
        lua_dir = os.path.relpath(runtime / 'lua', scripts).replace(os.sep, '/').encode()
        self._set_global(b'POB_CPATH', (cpath or default_cpath).encode())
        self._set_global(b'POB_SERVER_LUA', str(SERVER_LUA).encode())
        # The luajit executable sets `arg`; Main.lua reads arg[1] at startup.
        self._run(b"arg = {}\n"
                  b"package.path = '" + lua_dir + b"/?.lua;" + lua_dir + b"/?/init.lua;' .. package.path\n"
                  b"package.cpath = POB_CPATH .. ';' .. package.cpath\n"
                  b"dofile(POB_SERVER_LUA)", 0)

    def _set_global(self, name, value):
        self.lua.lua_pushlstring(self.state, value, len(value))
        self.lua.lua_setfield(self.state, LUA_GLOBALSINDEX, name)

    def _string(self, index):
        size = ctypes.c_size_t()
        pointer = self.lua.lua_tolstring(self.state, index, ctypes.byref(size))
        return ctypes.string_at(pointer, size.value).decode('utf-8', errors='replace') if pointer else ''

    def _run(self, chunk, results):
        lua = self.lua
        if lua.luaL_loadbuffer(self.state, chunk, len(chunk), b'=pob_server') or \
           lua.lua_pcall(self.state, 0, results, 0):
            message = self._string(-1)
            lua.lua_settop(self.state, 0)
            raise RuntimeError(message)

    def call(self, request):
        payload = json.dumps(request, ensure_ascii=False).encode('utf-8')
        lua = self.lua
        lua.lua_getfield(self.state, LUA_GLOBALSINDEX, b'pob_server_handle')
        lua.lua_pushlstring(self.state, payload, len(payload))
        failed = lua.lua_pcall(self.state, 1, 1, 0)
        text = self._string(-1)
        lua.lua_settop(self.state, 0)
        if failed:
            raise RuntimeError(text)
        return json.loads(text)


# Imported item lines such as "Fire Resistance is -10%" that PoB reads as a fixed
# resistance (ModParser "fire resistance is (%d+)%%" -> OVERRIDE) or not at all;
# the game has no such mod, it means "-10% to Fire Resistance" (an import tool wrote the line
# that way; see sources/assistant-shell.md, build.corrected_lines).
RESIST_IS = re.compile(r'^(\s*(?:\{[^}\n]*\})*)(Fire|Cold|Lightning|Chaos) Resistance is ([+-]?)(\d+)%([ \t\r]*)$',
                       re.MULTILINE | re.ASCII)  # Windows builds end lines with \r\n
# ASCII \s and \d: the same rule as PoB's src/Modules/AssistantBuildFixes.lua (B03, test_pob_resist_fix).


def correct_build(text):
    """Rewrite mistranslated resistance lines; returns (text, number of lines rewritten).
    The user's build file is not changed here; our PoB branch applies the same rule when it
    loads a build, so a build PoB has saved since then has nothing left to correct."""
    return RESIST_IS.subn(lambda m: f'{m[1]}{m[3] or "+"}{m[4]}% to {m[2]} Resistance{m[5]}', text)


def _stamp(path):
    info = path.stat()
    return info.st_mtime_ns, info.st_size


def find_live(user_dir):
    return pob_live.find(pob_live.live_dirs(user_dir))


class TrialServer:
    """Protocol state: which build is loaded and when to reload it.

    Without an explicit build, the build open in a running PoB (live snapshot,
    unsaved edits included) wins; otherwise the file PoB has open or opened last."""

    def __init__(self, engine, build=None, pob_user_dir=None, locator=locate, live_finder=find_live):
        self.engine = engine
        self.build = Path(build).resolve() if build else None
        self.pob_user_dir = pob_user_dir
        self.locator = locator
        self.live_finder = live_finder
        self.loaded = None  # (key, summary)

    def _target(self):
        """(key, source, path): the key changes whenever the build to load changes."""
        if self.build:
            return (self.build, _stamp(self.build)), 'explicit', self.build
        live = self.live_finder(self.pob_user_dir)
        if live:
            return ('live', live['file'], live['pid'], live['seq']), 'live', live['file']
        found = self.locator(self.pob_user_dir)
        path = Path(found['path']).resolve()
        return (path, _stamp(path)), found['source'], path

    def _read(self, source, path):
        """(xml text, engine build name, summary fields) for the target."""
        if source != 'live':
            return path.read_bytes().decode('utf-8'), path.stem, {'path': str(path), 'unsaved': False}
        snapshot = pob_live.read_snapshot(path)
        if not snapshot or snapshot['xml'] is None:
            raise ValueError('PoB 刚关闭了当前 BD，稍后再试')
        file = snapshot.get('path')
        return snapshot['xml'], snapshot.get('name') or 'PoB', {
            'path': str(Path(file).resolve()) if file else None, 'unsaved': bool(snapshot.get('unsaved')),
            'pob_pid': snapshot['pid'], 'live_seq': snapshot['seq']}

    def _load(self, key, source, path):
        text, name, fields = self._read(source, path)
        text, corrected = correct_build(text)
        summary = self.engine.call({'cmd': 'load', 'build_xml': text, 'name': name})
        if not summary.get('ok'):
            raise ValueError(summary.get('error', 'build load failed').splitlines()[0])
        summary.update(fields, source=source, corrected_lines=corrected)
        if source == 'live':  # PoB may have written a newer snapshot since _target
            key = ('live', path, fields['pob_pid'], fields['live_seq'])
        self.loaded = (key, summary)
        return summary

    def ensure_loaded(self):
        """Reload when the target or its version changed. Returns True if reloaded."""
        key, source, path = self._target()
        if self.loaded and self.loaded[0] == key:
            return False
        self._load(key, source, path)
        return True

    def handle(self, request):
        command = request.get('cmd')
        started = time.perf_counter()
        if command == 'load':
            if request.get('build'):
                self.build = Path(request['build']).resolve()
            else:
                self.build = None
            self.loaded = None
            self.ensure_loaded()
            result = dict(self.loaded[1])
        elif command == 'evaluate':
            if not isinstance(request.get('item_text'), str) or not request['item_text'].strip():
                raise ValueError('item_text 不能为空')
            reloaded = self.ensure_loaded()
            call = {'cmd': 'evaluate', 'item_text': request['item_text']}
            if request.get('slot'):
                call['slot'] = request['slot']
            result = self.engine.call(call)
            if not result.get('ok'):
                raise ValueError(result.get('error', 'evaluate failed').splitlines()[0])
            summary = self.loaded[1]
            result.update(build={'path': summary['path'], 'name': summary.get('build_name'),
                                 'source': summary['source'], 'unsaved': summary['unsaved'],
                                 'corrected_lines': summary['corrected_lines']},
                          reloaded=reloaded)
        else:
            raise ValueError('未知命令')
        result['elapsed_ms'] = round((time.perf_counter() - started) * 1000, 1)
        return result

    def serve(self, lines, out):
        for line in lines:
            if not line.strip():
                continue
            request_id = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('请求必须是 JSON 对象')
                request_id = request.get('id')
                response = self.handle(request)
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                response = {'ok': False, 'error': str(error)}
            response = {'id': request_id, **response}
            out.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + '\n')
            out.flush()


def add_server_arguments(parser):
    parser.add_argument('--engine', required=True, type=Path, help='固定 PoB 引擎根目录（含 src、runtime）')
    parser.add_argument('--lua-lib', type=Path, help='LuaJIT 动态库；Windows 默认 runtime/lua51.dll')
    parser.add_argument('--cpath', help='Lua C 模块搜索模式，默认与 LuaJIT 同目录')
    parser.add_argument('--build', type=Path, help='固定 BD 文件；省略时跟随 PoB 当前打开的 BD（含未保存的修改）')
    parser.add_argument('--pob-user-dir', type=Path, help='含 Settings.xml 的 PoB 用户目录')


def run_server_command(args):
    # Protocol lines go to a private copy of stdout; anything the engine
    # prints through fd 1 lands on stderr instead.
    out = os.fdopen(os.dup(1), 'w', encoding='utf-8', newline='\n')
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    build = args.build.resolve() if args.build else None
    user_dir = args.pob_user_dir.resolve() if args.pob_user_dir else None
    started = time.perf_counter()
    try:
        engine = LuaEngine(args.engine, args.lua_lib, args.cpath)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        out.write(json.dumps({'event': 'error', 'error': str(error)}, ensure_ascii=False) + '\n')
        return 1
    ready = {'event': 'ready', 'engine_commit': PIN,
             'init_ms': round((time.perf_counter() - started) * 1000, 1)}
    server = TrialServer(engine, build, user_dir)
    started = time.perf_counter()
    try:
        server.ensure_loaded()
        ready['build'] = {key: server.loaded[1][key] for key in ('path', 'source', 'build_name', 'unsaved')}
        ready['load_ms'] = round((time.perf_counter() - started) * 1000, 1)
    except (OSError, ValueError, RuntimeError) as error:
        ready['build_error'] = str(error)
    out.write(json.dumps(ready, ensure_ascii=False) + '\n')
    out.flush()
    stdin = open(sys.stdin.fileno(), encoding='utf-8', closefd=False)
    server.serve(stdin, out)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_server_arguments(parser)
    return run_server_command(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
