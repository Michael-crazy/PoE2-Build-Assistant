-- Run from the disposable upstream src directory, with upstream runtime on LUA_PATH.
local fixture, adapter, output = assert(arg[1]), assert(arg[2]), assert(arg[3])
io.read = function() error('unexpected interactive startup prompt') end
dofile('HeadlessWrapper.lua')
assert(build and not __mainObject__.promptMsg, 'engine startup failed')
local file = assert(io.open(fixture, 'r'))
local xml = file:read('*a')
file:close()
loadBuildFromXML(xml, 'P06 export checkpoint')
assert(not __mainObject__.promptMsg and not build.abortSave and not build.loadError, 'build load failed')
assert(#build.treeTab.specList == 2)
assert(build.skillsTab.skillSets[1].socketGroupList[1].gemList[1].gemData.gameId == 'Metadata/Items/Gem/SkillGemFireball')
assert(build.skillsTab.skillSets[2].socketGroupList[1].gemList[1].gemData.gameId == 'Metadata/Items/Gems/SkillGemSpark')
assert(build.itemsTab.items[1].base == data.itemBases['Gold Ring'])
assert(build.itemsTab.items[2].base == data.itemBases['Gold Ring'])
local before = assert(build:SaveDB('P06'))
local exporter = dofile(adapter)
for index, stage in ipairs({'leveling', 'endgame'}) do
    assert(exporter.write(build, output .. '/' .. stage .. '.build', {
        name = index == 1 and 'P06 开荒' or 'P06 终局',
        author = 'P06 验证', description = '完整引擎离线导出；双服客户端待验证',
        useGeneratedItemText = true,
    }, {specIndex = index, skillSetId = index, itemSetId = index}))
end
assert(build:SaveDB('P06') == before, 'export changed the loaded build')
print('P06: loaded XML; exported active and inactive sets; build unchanged')
