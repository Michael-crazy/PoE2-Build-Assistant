-- Resident PoB trial engine. Loaded once by pob_server.py inside the host
-- process (cwd = engine src). The host calls pob_server_handle(json) -> json.
local stderr = io.stderr
io.output(stderr)
print = function(...)
    local parts = {}
    for i = 1, select('#', ...) do parts[i] = tostring(select(i, ...)) end
    stderr:write(table.concat(parts, '\t'), '\n')
end
io.read = function() error('unexpected interactive input') end

local originalDofile = dofile
dofile = function(path)
    local result = originalDofile(path)
    if path == '_SimpleGraphic.def.lua' then
        LaunchSubScript = function() error('background scripts disabled') end
        OpenURL = function() error('URLs disabled') end
    end
    return result
end
originalDofile('HeadlessWrapper.lua')
dofile = originalDofile
assert(build and not __mainObject__.promptMsg, 'engine startup failed')
__mainObject__.DownloadPage = function() error('network disabled') end
__mainObject__.CheckForUpdate = function() error('updates disabled') end

local json = require('dkjson')
local xml = require('xml')

local KEYS = {'DPS', 'CombinedDPS', 'TotalEHP', 'Life', 'EnergyShield', 'Mana',
    'FireResist', 'ColdResist', 'LightningResist', 'ChaosResist'}
local SIGNED = {FireResist = true, ColdResist = true, LightningResist = true, ChaosResist = true}
local ATTRIBUTES = {'Str', 'Dex', 'Int'}
local RESISTS = {'Fire', 'Cold', 'Lightning', 'Chaos'}

-- DPS follows the sidebar: when the main skill summons a minion PoB shows
-- (and compares items by) the minion's CombinedDPS, else the player's.
local function dpsSource(env, output)
    return env.player.mainSkill.minion and output.Minion and 'minion' or 'player'
end

local function skillName(skill)
    return skill and skill.activeEffect and skill.activeEffect.grantedEffect.name or json.null
end

local function metrics(output, env)
    local result = {}
    for _, key in ipairs(KEYS) do
        local value = output[key]
        if key == 'DPS' then
            value = dpsSource(env, output) == 'minion' and output.Minion.CombinedDPS or output.CombinedDPS
        end
        assert(type(value) == 'number' and value == value and value > -math.huge and value < math.huge
            and (SIGNED[key] or value >= 0), 'invalid metric ' .. key)
        result[key] = value
    end
    local attributes, met = {}, true
    for _, attr in ipairs(ATTRIBUTES) do
        local value, required = output[attr] or 0, output['Req' .. attr] or 0
        local gap = math.max(0, required - value)
        attributes[attr] = {value = value, required = required, gap = gap}
        met = met and gap == 0
    end
    result.attributes = attributes
    -- CalcDefence: Resist = clamp(ResistTotal, min, max) and
    -- MissingResist = max - Resist, so the cap is their sum.
    local resists = {}
    for _, elem in ipairs(RESISTS) do
        local value = output[elem .. 'Resist']
        resists[elem] = {value = value, max = value + output['Missing' .. elem .. 'Resist'],
            total = output[elem .. 'ResistTotal'], overcap = output[elem .. 'ResistOverCap']}
    end
    result.resists = resists
    result.requirements_met = met
    return result
end

local state = {}

-- The misc calculator returns only output; capture the env it builds so
-- the effective item list (two-handers displacing the offhand, etc.) comes
-- from the engine instead of re-implementing CalcSetup's rules.
local calcsModule = build.calcsTab.calcs
local originalInitEnv = calcsModule.initEnv
-- initEnv can recurse; keep the first env finished at the outermost level.
local depth = 0
local function captureEnv(env, ...)
    depth = depth - 1
    if depth == 0 then state.env = state.env or env end
    return env, ...
end
calcsModule.initEnv = function(...)
    depth = depth + 1
    return captureEnv(originalInitEnv(...))
end

-- Full DPS is skipped (second argument false): it re-runs every skill and
-- the overlay reports CombinedDPS of the main skill.
local function calculate(override)
    state.env = nil
    local output = state.calculator(override, false)
    local items = {}
    for slot, item in pairs(state.env.player.itemList) do items[slot] = item end
    return metrics(output, state.env), items
end

local function skillInfo()
    local env = state.baseEnv
    local source = dpsSource(env, env.player.output)
    return {dps_source = source, main_skill = skillName(env.player.mainSkill),
        minion_skill = source == 'minion' and env.minion and skillName(env.minion.mainSkill) or json.null}
end

local function candidateSlots(item, only)
    local env = build.calcsTab.mainEnv
    -- Socket visibility is refreshed on Draw; headless, refresh it the way
    -- the item compare tooltip does so unallocated sockets stay hidden.
    build.itemsTab:UpdateSockets()
    local slots = {}
    for _, control in ipairs(build.itemsTab.orderedSlots) do
        local name = control.slotName
        -- Weapon slots follow the main skill's calculated set, not the set the
        -- items UI shows; other slots use PoB's own visibility (e.g. Ring 3
        -- needs AdditionalRingSlot, jewel sockets need an allocated node).
        local active
        if control.weaponSet then
            active = control.weaponSet == env.weaponSet and not control.inactive
        else
            active = control:GetProperty('shown')
        end
        if (not only or only == name) and active
            and build.itemsTab:IsItemValidForSlot(item, name) then
            slots[#slots + 1] = control
        end
    end
    return slots
end

local function load(request)
    assert(type(request.build_xml) == 'string', 'missing build_xml')
    local parsed, xmlError = xml.ParseXML(request.build_xml)
    assert(parsed and parsed[1] and parsed[1].elem == 'PathOfBuilding2', xmlError or 'invalid build XML')
    state.calculator = nil
    loadBuildFromXML(request.build_xml, request.name or 'Trial')
    assert(not __mainObject__.promptMsg and not build.abortSave and not build.loadError, 'build load failed')
    state.calculator = build.calcsTab:GetMiscCalculator()
    state.baseline, state.items = calculate()
    state.baseEnv = state.env
    local equipped = {}
    for slot, item in pairs(state.items) do equipped[slot] = item.name end
    return {build_name = build.buildName, weapon_set = build.calcsTab.mainEnv.weaponSet,
        baseline = state.baseline, equipped = equipped, skill = skillInfo()}
end

local function evaluate(request)
    assert(state.calculator, 'no build loaded')
    assert(type(request.item_text) == 'string' and request.item_text:match('%S'), 'missing item_text')
    local item = new('Item'):Item(request.item_text)
    assert(item.base, 'unrecognized item base')
    local slots = candidateSlots(item, request.slot)
    assert(#slots > 0, request.slot and ('item cannot go in slot ' .. request.slot)
        or 'no active slot accepts this item')
    local rows = {}
    for _, control in ipairs(slots) do
        local after, items = calculate({repSlotName = control.slotName, repItem = item})
        local delta = {}
        for _, key in ipairs(KEYS) do delta[key] = after[key] - state.baseline[key] end
        local target = control.slotName:gsub(' Swap$', '')
        local displaced = {}
        for slot, old in pairs(state.items) do
            if slot ~= target and items[slot] ~= old then
                displaced[#displaced + 1] = {slot = slot, name = old.name}
            end
        end
        table.sort(displaced, function(a, b) return a.slot < b.slot end)
        local replaced = state.items[target]
        rows[#rows + 1] = {slot = control.slotName, replaced = replaced and replaced.name or json.null,
            displaced = setmetatable(displaced, {__jsontype = 'array'}),
            metrics = after, delta = delta}
    end
    return {item = {name = item.name, base = item.baseName, type = item.type, rarity = item.rarity},
        baseline = state.baseline, slots = rows, skill = skillInfo()}
end

local handlers = {load = load, evaluate = evaluate}

function pob_server_handle(payload)
    local ok, result = xpcall(function()
        local request, _, err = json.decode(payload)
        assert(not err and type(request) == 'table', err or 'invalid request')
        local handler = assert(handlers[request.cmd], 'unknown command')
        return handler(request)
    end, debug.traceback)
    if not ok then
        return assert(json.encode({ok = false, error = tostring(result)}))
    end
    result.ok = true
    return assert(json.encode(result))
end
