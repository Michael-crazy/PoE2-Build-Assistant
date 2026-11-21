-- Test helper for scripts/test_wegame_import.py (U07): a headless PoB from our branch imports a
-- WeGame share through the import tab's own path (fetch -> convert -> PoB character import), runs
-- the calculations, saves the build and loads it again. Run with cwd = <engine>/src and
--   U07_BUNDLE      fixture bundle; launch:DownloadPage answers from it (no network)
--   U07_USER        writable directory used as PoB's user path
--   POE2_ASSISTANT_PYTHON / POE2_ASSISTANT_BACKEND_SCRIPTS   the converter (SpawnProcess runs it
--                   synchronously here)
-- Prints one JSON object on stdout.
local reply = io.stdout
io.output(io.stderr)
print = function(...)
	local parts = { }
	for i = 1, select("#", ...) do parts[i] = tostring(select(i, ...)) end
	io.stderr:write(table.concat(parts, "\t"), "\n")
end

dofile("HeadlessWrapper.lua")
local dkjson = require("dkjson")
local main = __mainObject__.main
main.userPath = os.getenv("U07_USER") .. "/"

local file = assert(io.open(os.getenv("U07_BUNDLE"), "rb"))
local bundle = dkjson.decode(file:read("*a"))
file:close()
local answers = { GetRoleInfo = "role_info", GetEquipments = "equipments", GetTalentTree = "talent_tree", GetJewels = "jewels", GetSkills = "skills" }
local requests = { }
function launch:DownloadPage(url, callback, params)
	local method = url:match("Profile/(%w+)$")
	requests[#requests + 1] = { method = method, body = dkjson.decode(params.body), header = params.header }
	callback({ body = dkjson.encode(bundle[answers[method]] or { }) }, nil)
end
function MakeDir(path)
	os.execute('mkdir -p "' .. path .. '"')
end
function SpawnProcess(command, args)
	os.execute('"' .. command .. '" ' .. args)
end

local consoleLines = { }
local conPrintf = ConPrintf
ConPrintf = function(fmt, ...)
	local ok, text = pcall(string.format, fmt, ...)
	consoleLines[#consoleLines + 1] = ok and text or fmt
	return conPrintf(fmt, ...)
end

local function snapshot(b)
	local slots = { }
	for name, slot in pairs(b.itemsTab.slots) do
		local item = slot.selItemId ~= 0 and b.itemsTab.items[slot.selItemId]
		if item then
			slots[name] = { name = item.name, base = item.baseName, rarity = item.rarity, lines = #item.explicitModLines + #item.implicitModLines, runes = item.runes and #item.runes or 0 }
		end
	end
	local groups = { }
	for _, group in ipairs(b.skillsTab.socketGroupList) do
		local gems = { }
		for _, gem in ipairs(group.gemList) do
			gems[#gems + 1] = { name = gem.nameSpec, level = gem.level, ok = gem.gemData ~= nil }
		end
		groups[#groups + 1] = gems
	end
	local allocated = 0
	for _ in pairs(b.spec.allocNodes) do
		allocated = allocated + 1
	end
	local output = b.calcsTab.mainOutput or { }
	return {
		class = b.spec.curClassName, ascendancy = b.spec.curAscendClassName, level = b.characterLevel,
		allocated = allocated, slots = slots, groups = groups,
		output = { Life = output.Life, EnergyShield = output.EnergyShield, Mana = output.Mana, Spirit = output.Spirit, Str = output.Str, Dex = output.Dex, Int = output.Int, Armour = output.Armour, Evasion = output.Evasion, FireResist = output.FireResist, ColdResist = output.ColdResist, LightningResist = output.LightningResist, ChaosResist = output.ChaosResist },
	}
end

newBuild()
local importTab = build.importTab
importTab.controls.weGameLink:SetText("https://www.wegame.com.cn/helper/poe2/#/share/" .. string.rep("A", 40))
local ok, err = pcall(function()
	importTab:ImportWeGame(true, true)
	for _ = 1, 20 do
		if not importTab.weGameBusy then
			break
		end
		build.viewMode = "IMPORT"
		runCallback("OnFrame")
	end
	build.calcsTab:BuildOutput()
	runCallback("OnFrame")
end)
local result = { ok = ok, error = not ok and tostring(err) or nil, status = build.importTab.weGameStatus, prompt = __mainObject__.promptMsg, requests = requests }
if ok then
	result.imported = snapshot(build)
	local xml = build:SaveDB("code")
	result.xmlBytes = #xml
	local reloadOk, reloadErr = pcall(function()
		loadBuildFromXML(xml, "reload")
		build.calcsTab:BuildOutput()
		runCallback("OnFrame")
	end)
	result.reloadOk = reloadOk
	result.reloadError = not reloadOk and tostring(reloadErr) or nil
	if reloadOk then
		result.reloaded = snapshot(build)
	end
	local out = os.getenv("U07_XML_OUT")
	if out then
		local f = io.open(out, "wb")
		f:write(xml)
		f:close()
	end
end
result.console = { }
for _, line in ipairs(consoleLines) do
	if line:find("WeGame", 1, true) or line:find("Unrecognised", 1, true) then
		result.console[#result.console + 1] = line
	end
end
reply:write(dkjson.encode(result), "\n")
reply:flush()
os.exit(0)
