-- One request per process. Run only through pob_worker.py and pob_trial.py.
local stdout = io.stdout
io.output(io.stderr)
print = function(...)
    local parts = {}
    for i = 1, select('#', ...) do parts[i] = tostring(select(i, ...)) end
    io.stderr:write(table.concat(parts, '\t'), '\n')
end
local function main()
    local json = require('dkjson')
    local payload = io.stdin:read('*a')
    local request, position, err = json.decode(payload)
    assert(not err and type(request) == 'table', err or 'invalid request')
    assert(not payload:sub(position):match('%S'), 'trailing request data')
    local inventoryRequest = request.protocol == 'pob-inventory/1'
    local itemRequest = request.protocol == 'pob-item/1'
    assert(inventoryRequest or itemRequest or request.protocol == 'pob-trial/1', 'unsupported protocol')
    assert(request.engine_commit == os.getenv('POB_ENGINE_COMMIT'), 'engine mismatch')
    assert(itemRequest or type(request.build_xml) == 'string', 'missing XML')
    assert(not itemRequest or type(request.raw_text) == 'string', 'missing item text')
    assert(inventoryRequest or itemRequest or type(request.replacement) == 'table', 'missing replacement')
    -- Fail closed if the wrapper tries to wait on an initialization prompt.
    io.read = function() error('unexpected interactive input') end
    -- HeadlessWrapper installs the SimpleGraphic definitions before Launch.lua.
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
    assert(build and not __mainObject__.promptMsg, 'engine startup failed')
    __mainObject__.DownloadPage = function() error('network disabled') end
    __mainObject__.CheckForUpdate = function() error('updates disabled') end
    if itemRequest then
        -- Report how PoB reads one item: base, affix IDs and each line's parse.
        local item = new('Item'):Item(request.raw_text)
        local function lines(list)
            local out = {}
            for _, modLine in ipairs(list) do
                -- Base implicits and later lines of hybrid affixes keep a range
                -- template plus a roll; value is the line PoB computes from them.
                out[#out + 1] = {line = modLine.line, mods = #(modLine.modList or {}),
                    value = itemLib.applyRange(modLine.line, modLine.range or _G.main.defaultItemAffixQuality or 1,
                        modLine.valueScalar),
                    extra = modLine.extra and tostring(modLine.extra) or json.null}
            end
            return out
        end
        local function affixes(list)
            local out = {}
            for _, affix in ipairs(list) do
                out[#out + 1] = {mod_id = affix.modId, range = type(affix.range) == 'number' and affix.range or json.null}
            end
            return out
        end
        stdout:write(assert(json.encode({protocol = request.protocol, engine_commit = request.engine_commit,
            request_sha256 = require('sha2').sha256(payload), name = item.name or json.null,
            base_name = item.baseName or json.null, rarity = item.rarity or json.null,
            quality = item.quality or json.null, item_level = item.itemLevel or json.null,
            corrupted = not not item.corrupted, desecrated = not not item.desecrated,
            requirements = {level = item.requirements.level or json.null},
            sockets = #item.sockets, armour = item.armourData or json.null,
            prefixes = affixes(item.prefixes or {}), suffixes = affixes(item.suffixes or {}),
            rune_lines = lines(item.runeModLines), enchant_lines = lines(item.enchantModLines),
            implicit_lines = lines(item.implicitModLines),
            explicit_lines = lines(item.explicitModLines)})), '\n')
        return
    end
    local xml = require('xml')
    local parsed, xmlError = xml.ParseXML(request.build_xml)
    assert(parsed and parsed[1] and parsed[1].elem == 'PathOfBuilding2', xmlError or 'invalid build XML')
    loadBuildFromXML(request.build_xml, 'Offline trial')
    assert(not __mainObject__.promptMsg and not build.abortSave and not build.loadError, 'build load failed')
    if inventoryRequest then
        -- Keep XML selection IDs before PoB normalizes incompatible equipment.
        local stored, itemSetId = {}, nil
        for _, section in ipairs(parsed[1]) do
            if type(section) == 'table' and section.elem == 'Items' then
                itemSetId = section.attrib.activeItemSet or '1'
                for _, itemSet in ipairs(section) do
                    if type(itemSet) == 'table' and itemSet.elem == 'ItemSet' and itemSet.attrib.id == itemSetId then
                        for _, entry in ipairs(itemSet) do
                            if type(entry) == 'table' and entry.elem == 'Slot' then
                                stored[entry.attrib.name] = tonumber(entry.attrib.itemId) or 0
                            end
                        end
                    end
                end
            end
        end
        local env = build.calcsTab.mainEnv
        -- Read the loaded spec and calculated flags, not XML declarations.
        local nodes = {}
        for id, node in pairs(env.spec.allocNodes) do
            nodes[#nodes + 1] = {id = id, name = node.dn,
                calculated = env.allocNodes[id] ~= nil,
                additional_ring_slot = not not node.modList:Flag(nil, 'AdditionalRingSlot')}
        end
        table.sort(nodes, function(a, b) return a.id < b.id end)
        local passiveSpec = {tree_version = env.spec.treeVersion,
            class_id = env.spec.curClassId, ascend_class_id = env.spec.curAscendClassId,
            class_name = env.spec.curClassName, ascend_class_name = env.spec.curAscendClassName,
            allocated_nodes = nodes,
            additional_ring_slot = not not env.modDB:Flag(nil, 'AdditionalRingSlot')}
        local rows = {}
        for _, control in ipairs(build.itemsTab.orderedSlots) do
            local name = control.slotName
            local selected = build.itemsTab.items[control.selItemId]
            local storedId = stored[name] or 0
            -- Include all base slots and occupied dynamic sockets, not hundreds
            -- of unavailable empty jewel sockets.
            if not control.nodeId and not control.parentSlot or selected or storedId ~= 0 then
                local calcName = name:gsub(' Swap', '')
                local effective = env.player.itemList[calcName]
                local consumable = selected and (selected.type == 'Flask' or selected.type == 'Charm')
                local effectActive = consumable and not not (env.flasks[selected] or env.charms[selected])
                local state
                if control.weaponSet and control.weaponSet ~= env.weaponSet then
                    state = 'inactive_weapon_set'
                    effective = nil
                elseif storedId ~= 0 and not selected then
                    state = 'engine_removed'
                elseif control.inactive then
                    state = 'inactive_slot'
                elseif selected and effective == selected then
                    state = 'equipped'
                elseif consumable then
                    -- CalcSetup removes consumables from player.itemList. A
                    -- non-active flask/charm is not proof of exclusion or use.
                    state = effectActive and 'equipped' or 'stored_consumable'
                elseif selected then
                    state = 'engine_excluded'
                else
                    state = 'empty'
                end
                rows[#rows + 1] = {slot = name, state = state,
                    stored_item_id = tostring(storedId), selected_item_id = tostring(control.selItemId or 0),
                    effective_item_id = state == 'equipped' and tostring(selected.id) or json.null,
                    effect_active = consumable and effectActive or false}
            end
        end
        stdout:write(assert(json.encode({protocol = request.protocol, engine_commit = request.engine_commit,
            request_sha256 = require('sha2').sha256(payload), item_set_id = itemSetId,
            weapon_set = env.weaponSet, inventory = rows, passive_spec = passiveSpec})), '\n')
        return
    end
    local slot = request.replacement.slot
    local slotControl = build.itemsTab.slots[slot]
    assert(slotControl and not slotControl.inactive, 'unknown or inactive slot')
    -- Weapon slots use weaponSet, not inactive. Follow the main skill's
    -- calculated set (which can differ from the set shown in the items UI).
    assert(not slotControl.weaponSet or slotControl.weaponSet == build.calcsTab.mainEnv.weaponSet,
        'slot outside calculated weapon set')
    local item = new('Item'):Item(request.replacement.raw_text)
    assert(item.base and build.itemsTab:IsItemValidForSlot(item, slot), 'item incompatible with slot')
    local keys = {'CombinedDPS', 'Life', 'EnergyShield', 'Armour', 'Evasion'}
    local function metrics(output)
        local result = {}
        for _, key in ipairs(keys) do
            local value = output[key]
            assert(type(value) == 'number' and value == value and value >= 0 and value < math.huge, 'invalid metric ' .. key)
            result[key] = value
        end
        return result
    end
    local calculate = build.calcsTab:GetMiscCalculator()
    local baseline = metrics(calculate())
    local replacement = metrics(calculate({repSlotName = slot, repItem = item}))
    local restored = metrics(calculate())
    for _, key in ipairs(keys) do assert(restored[key] == baseline[key], 'baseline changed: ' .. key) end
    local response = {protocol = request.protocol, engine_commit = request.engine_commit,
        request_sha256 = require('sha2').sha256(payload), baseline = baseline, replacement = replacement}
    stdout:write(assert(json.encode(response)), '\n')
end
local ok, err = xpcall(main, debug.traceback)
if not ok then io.stderr:write(tostring(err), '\n'); os.exit(1) end
