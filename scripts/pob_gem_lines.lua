-- Dump PoB's English gem tooltip stat lines (as GemTooltip.lua builds them) for D02.
-- Run from the PoB src directory with the upstream runtime on LUA_PATH: luajit pob_gem_lines.lua <output.json>
local output = assert(arg[1])
io.read = function() error('unexpected interactive startup prompt') end
dofile('HeadlessWrapper.lua')
assert(build and not __mainObject__.promptMsg, 'engine startup failed')
local dkjson = require('dkjson')

local function statLines(grantedEffect, statSet, level)
    local instance = { quality = 0, level = level }
    local stats = calcLib.buildSkillInstanceStats(instance, grantedEffect, statSet)
    local lines = data.describeStats(stats, statSet.statDescriptionScope)
    local out = { }
    for i, line in ipairs(lines) do out[i] = line end
    return out
end

local function qualityLines(grantedEffect)
    local out = { }
    for _, stat in ipairs(grantedEffect.qualityStats or { }) do
        local statSet = grantedEffect.statSets[(stat[3] and stat[3][1] or 0) + 1] or grantedEffect.statSets[1]
        for _, line in ipairs(data.describeStats({ [stat[1]] = 20 * stat[2] }, statSet.statDescriptionScope, true)) do
            out[#out + 1] = line
        end
    end
    return out
end

local function effect(grantedEffect)
    local levels = { }
    for level in pairs(grantedEffect.levels) do levels[#levels + 1] = level end
    table.sort(levels)
    -- lowest level, level 20 (the usual uncut maximum, used by the value check) and the highest level
    local picked = { levels[1] }
    if grantedEffect.levels[20] and levels[1] ~= 20 then picked[#picked + 1] = 20 end
    if levels[#levels] ~= picked[#picked] then picked[#picked + 1] = levels[#levels] end
    local sets = { }
    for index, statSet in ipairs(grantedEffect.statSets or { }) do
        local byLevel = { }
        for _, level in ipairs(picked) do byLevel[tostring(level)] = statLines(grantedEffect, statSet, level) end
        sets[index] = { label = statSet.label, lines = byLevel }
    end
    return { id = grantedEffect.id, name = grantedEffect.name, description = grantedEffect.description,
             support = grantedEffect.support or false, castTime = grantedEffect.castTime,
             statSets = sets, quality = qualityLines(grantedEffect) }
end

local gems = { }
for gemId, gem in pairs(data.gems) do
    local effects = { effect(gem.grantedEffect) }
    for _, extra in ipairs(gem.additionalGrantedEffects or { }) do effects[#effects + 1] = effect(extra) end
    local tags = { }
    for tag in pairs(gem.tags or { }) do tags[#tags + 1] = tag end
    table.sort(tags)
    gems[gemId] = { name = gem.name, gameId = gem.gameId, tagString = gem.tagString, tags = tags, effects = effects }
end
local file = assert(io.open(output, 'w'))
file:write(dkjson.encode(gems, { keyorder = { } }))
file:close()
print('gem lines: ' .. output)
