"""Worker control-flow tests use Lua 5.4 stubs, never the PoB engine."""
import ctypes
import ctypes.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pob_worker import prepare

WORKER = Path(__file__).with_name('pob_worker.lua').resolve()


class LauncherTests(unittest.TestCase):
    def test_rejects_wrong_or_dirty_engine_before_copy(self):
        for values in (['wrong', ''], ['601768bd105869618c3d6581b883e5d7aeec91b2', ' M src/Launch.lua']):
            with tempfile.TemporaryDirectory() as directory, \
                 patch('pob_worker.subprocess.check_output', side_effect=values), \
                 patch('pob_worker.shutil.copytree') as copy:
                with self.assertRaises(ValueError):
                    prepare(directory, Path(directory) / 'copy')
                copy.assert_not_called()


@unittest.skipUnless(ctypes.util.find_library('lua5.4'), 'Lua 5.4 shared library unavailable; stub test only')
class LuaWorkerTests(unittest.TestCase):
    def test_worker_control_flow(self):
        lua = ctypes.CDLL(ctypes.util.find_library('lua5.4'))
        lua.luaL_newstate.restype = ctypes.c_void_p
        lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lua.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lua.lua_pcallk.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_longlong, ctypes.c_void_p]
        lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lua.lua_tolstring.restype = ctypes.c_char_p
        lua.lua_close.argtypes = [ctypes.c_void_p]
        harness = r'''
local worker = dofile
local mode = MODE
local result, output, errors
local req = {protocol='pob-trial/1', engine_commit='pin', build_xml='<PathOfBuilding2/>',
    replacement={slot='Weapon 1', raw_text='item'}}
if mode == 'protocol' then req.protocol = 'bad' end
if mode == 'inventory' then req.protocol = 'pob-inventory/1'; req.replacement = nil end
os.getenv = function() return 'pin' end
os.exit = function(code) error('exit ' .. code) end
io.stdin = {read=function() return 'original bytes' end}
io.stdout = {write=function(_, text) output = text end}
io.stderr = {write=function(_, text) errors = text end}
io.output = function() end
package.preload.dkjson = function() return {
    decode=function() return req, 15 end,
    encode=function(value) result=value; return 'encoded' end} end
package.preload.sha2 = function() return {sha256=function(value)
    assert(value == 'original bytes'); return 'digest' end} end
package.preload.xml = function() return {ParseXML=function()
    return {{elem=mode == 'xml' and 'wrong' or 'PathOfBuilding2'}} end} end
local calls = 0
local function metric(value) return {CombinedDPS=value, Life=100, EnergyShield=0, Armour=1, Evasion=2} end
dofile = function(path)
    assert(path == 'HeadlessWrapper.lua')
    __mainObject__ = {}
    build = {itemsTab={slots={['Weapon 1']={inactive=mode == 'inactive',
        weaponSet=mode == 'other_weapon_set' and 2 or 1}},
        IsItemValidForSlot=function() return mode ~= 'incompatible' end},
        calcsTab={mainEnv={weaponSet=1}, GetMiscCalculator=function() return function(override)
            calls = calls + 1
            if mode == 'mutated' and calls == 3 then return metric(999) end
            if mode == 'missing' then return {} end
            return metric(override and 120 or 100)
        end end}}
    if mode == 'inventory' then
        local item = {id=7}
        build.itemsTab.items = {[7]=item}
        build.itemsTab.orderedSlots = {
            {slotName='Weapon 2', selItemId=7, weaponSet=1},
            {slotName='Weapon 2 Swap', selItemId=7, weaponSet=2},
            {slotName='Ring 3', selItemId=7},
        }
        build.calcsTab.mainEnv.player = {itemList={['Weapon 2']=item}}
        build.calcsTab.mainEnv.spec = {allocNodes={}}
        build.calcsTab.mainEnv.modDB = {Flag=function() return false end}
    end
    loadBuildFromXML = function(value) assert(value == req.build_xml) end
    new = function(name) assert(name == 'Item'); return {Item=function() return {base={}} end} end
end
local ok = pcall(worker, WORKER)
if mode == 'inventory' then
    assert(ok, errors)
    assert(output == 'encoded' and calls == 0)
    assert(result.inventory[1].state == 'equipped' and result.inventory[1].effective_item_id == '7')
    assert(result.inventory[2].state == 'inactive_weapon_set')
    assert(result.inventory[3].state == 'engine_excluded')
    assert(result.passive_spec.additional_ring_slot == false)
elseif mode == 'ok' then
    assert(ok, errors)
    assert(output == 'encoded' and calls == 3)
    assert(result.baseline.CombinedDPS == 100 and result.replacement.CombinedDPS == 120)
    assert(result.request_sha256 == 'digest' and result.engine_commit == 'pin')
else assert(not ok and output == nil, 'failure must not emit response: ' .. mode) end
'''
        for mode in ('ok', 'inventory', 'protocol', 'xml', 'inactive', 'other_weapon_set', 'incompatible', 'mutated', 'missing'):
            with self.subTest(mode=mode):
                state = lua.luaL_newstate()
                try:
                    lua.luaL_openlibs(state)
                    source = "local MODE = '%s'; local WORKER = '%s';\n" % (mode, WORKER) + harness
                    status = lua.luaL_loadstring(state, source.encode())
                    if not status:
                        status = lua.lua_pcallk(state, 0, 0, 0, 0, None)
                    self.assertEqual(status, 0, lua.lua_tolstring(state, -1, None))
                finally:
                    lua.lua_close(state)
