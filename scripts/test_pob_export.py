"""Execute the pinned upstream exporter, using authored build objects, not a client."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = Path(os.environ.get('POB_EXPORT_ENGINE', '/tmp/poe2-pob-source'))
LUA = Path(os.environ.get('POB_EXPORT_LUA', str(Path.home() / '.local/state/poe2-assistant/p02-runtime/LuaJIT/src/luajit')))


@unittest.skipUnless(ENGINE.is_dir() and LUA.is_file(), 'pinned engine and LuaJIT required')
class ExportTests(unittest.TestCase):
    def test_upstream_stage_files(self):
        pin = json.loads((ROOT / 'sources/pob.json').read_text())['commit']
        self.assertEqual(subprocess.check_output(['git', '-C', str(ENGINE), 'rev-parse', 'HEAD'], text=True).strip(), pin)
        self.assertEqual(subprocess.check_output(['git', '-C', str(ENGINE), 'status', '--porcelain'], text=True), '')
        source = r'''
package.path = arg[1] .. '/src/?.lua;' .. arg[1] .. '/runtime/lua/?.lua;' .. package.path
local adapter = dofile(arg[2])
data = {buildFileInventorySlotMap=dofile(arg[1] .. '/src/Data/InventorySlots.lua')}
ConPrintf = function(...) error('unexpected missing game ID') end
local function skill(id, note)
    return {enabled=true, note=note, gemData={gameId=id, grantedEffectList={{support=false}}}}
end
local a = skill('Fireball', '开荒技能')
local b = skill('Fireball', '终局技能')
local support = {enabled=true, level=1, quality=0,
    gemData={gameId='SupportAddedFireDamage', grantedEffect={support=true}, grantedEffectList={{support=true}}}}
local build = {buildName='阶段测试',
    treeTab={specList={
        {allocNodes={[10]={stringId='test-passive-early',allocMode=0}},nodeNotes={[10]='开荒天赋'}},
        {allocNodes={[20]={stringId='test-passive-final',allocMode=1}},nodeNotes={[20]='终局天赋'}}}},
    skillsTab={skillSets={
        [11]={socketGroupList={{gemList={a,support}}}},
        [22]={socketGroupList={{gemList={b}}}}}},
    itemsTab={items={},itemSets={
        [11]={['Ring 1']={note='开荒戒指'}},
        [22]={['Ring 2']={note='终局戒指'}}}}}
for index, id in ipairs({11,22}) do
    local selection={specIndex=index,skillSetId=id,itemSetId=id}
    assert(adapter.write(build, arg[3] .. '/' .. index .. '.build',
        {name='阶段 ' .. index,author='作者',description='中文备注',useGeneratedItemText=false},selection))
end
assert(not pcall(adapter.write,build,arg[3] .. '/invalid.build',{},
    {specIndex=3,skillSetId=11,itemSetId=11}))
assert(not pcall(adapter.write,build,arg[3] .. '/missing.build',{},{}))
assert(not pcall(adapter.write,build,arg[3] .. '/wrong.xml',{},{}))
local ok = adapter.write(build,arg[3] .. '/absent/file.build',{},
    {specIndex=1,skillSetId=11,itemSetId=11})
assert(not ok)
assert(build.treeTab.specList[1].nodeNotes[10] == '开荒天赋')
assert(build.itemsTab.itemSets[11]['Ring 1'].note == '开荒戒指')
local empty = {treeTab={specList={{}}}, skillsTab={skillSets={[1]={}}},itemsTab={itemSets={[1]={}}}}
assert(adapter.write(empty,arg[3] .. '/empty.build',{}, {specIndex=1,skillSetId=1,itemSetId=1}))
'''
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'test.lua'
            harness.write_text(source)
            subprocess.run([str(LUA), str(harness), str(ENGINE), str(ROOT / 'scripts/pob_export.lua'), directory], check=True, timeout=20)
            for index, stage in ((1, 'early'), (2, 'final')):
                value = json.loads((Path(directory) / f'{index}.build').read_text())
                self.assertEqual(value['name'], f'阶段 {index}')
                self.assertEqual(value['description'], '中文备注')
                self.assertIsInstance(value['passives'], list)
                self.assertIsInstance(value['skills'], list)
                self.assertIsInstance(value['inventory_slots'], list)
                self.assertEqual(value['passives'][0]['id'], f'test-passive-{stage}')
                self.assertEqual(value['passives'][0]['weapon_set'], index - 1)
                self.assertEqual(value['inventory_slots'][0]['inventory_id'], f'Ring{index}')
                self.assertEqual(value['skills'][0]['id'], 'Fireball')
                if index == 1:
                    self.assertEqual(value['skills'][0]['support_skills'], ['SupportAddedFireDamage'])
                else:
                    self.assertNotIn('support_skills', value['skills'][0])
            empty = json.loads((Path(directory) / 'empty.build').read_text())
            for key in ('passives', 'skills', 'inventory_slots'):
                self.assertEqual(empty[key], [])
            self.assertFalse((Path(directory) / 'invalid.build').exists())
