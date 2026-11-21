-- Test helper for scripts/test_pob_command.py: a headless PoB from our branch
-- that publishes its build (U02) and takes assistant commands (U06) the way
-- the real application does. Run with cwd = <engine>/src:
--   luajit pob_command_driver.lua <live dir> <command dir> <build.xml>
-- Then one command per stdin line, each answered by "@@done" on stdout:
--   frame   run one frame (takes a pending command)
--   items   print the item list as one JSON line, then run a frame
--   close   close the build (back to the build list)
assistantLiveDir = arg[1]
assistantCommandDir = arg[2]
local buildFile = arg[3]
local reply = io.stdout
io.output(io.stderr)
print = function(...)
	local parts = { }
	for i = 1, select("#", ...) do parts[i] = tostring(select(i, ...)) end
	io.stderr:write(table.concat(parts, "\t"), "\n")
end

dofile("HeadlessWrapper.lua")
local dkjson = require("dkjson")
local file = assert(io.open(buildFile, "rb"))
local xmlText = file:read("*a")
file:close()
loadBuildFromXML(xmlText, "command-test")
runCallback("OnFrame")
build.itemsTab.modFlag = false -- as if just opened from its file
build.modFlag = false
runCallback("OnFrame")
reply:write("@@ready\n")
reply:flush()

local function items()
	local itemsTab = build.itemsTab
	local list = { }
	for _, id in ipairs(itemsTab.itemOrderList) do
		local item = itemsTab.items[id]
		local equipped = false
		for _, slot in pairs(itemsTab.slots) do
			if slot.selItemId == id then
				equipped = true
			end
		end
		list[#list + 1] = { id = id, title = item.title or dkjson.null, name = item.name, baseName = item.baseName,
			equipped = equipped, raw = item:BuildRaw() }
	end
	local selected = itemsTab.controls.itemList.selValue
	return dkjson.encode({ items = list, unsaved = build.unsaved and true or false,
		itemsModified = itemsTab.modFlag and true or false, selected = selected or dkjson.null })
end

for line in io.lines() do
	if line == "items" then
		reply:write(items(), "\n")
	elseif line == "close" then
		__mainObject__.main:SetMode("LIST")
	end
	runCallback("OnFrame")
	reply:write("@@done\n")
	reply:flush()
end
