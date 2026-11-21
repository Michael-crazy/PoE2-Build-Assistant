-- Test helper for scripts/test_pob_live.py: a headless PoB from our branch that
-- publishes its open build the way the real application does (the global
-- assistantLiveDir switches AssistantLiveBuild.lua on). Run with cwd = <engine>/src:
--   luajit pob_live_driver.lua <live dir> <build.xml>
-- Then one command per stdin line, each answered by "@@done" on stdout:
--   level <n>   set the character level by hand (an unsaved edit)
--   close       close the build (back to the build list)
assistantLiveDir = arg[1]
local buildFile = arg[2]
local reply = io.stdout
io.output(io.stderr)
print = function(...)
	local parts = { }
	for i = 1, select("#", ...) do parts[i] = tostring(select(i, ...)) end
	io.stderr:write(table.concat(parts, "\t"), "\n")
end

dofile("HeadlessWrapper.lua")
local file = assert(io.open(buildFile, "rb"))
local xmlText = file:read("*a")
file:close()
loadBuildFromXML(xmlText, "live-test")
runCallback("OnFrame")
reply:write("@@ready\n")
reply:flush()

for line in io.lines() do
	local level = line:match("^level (%d+)$")
	if level then
		build.characterLevel = tonumber(level)
		build.characterLevelAutoMode = false
		build.modFlag = true
		build.buildFlag = true
	elseif line == "close" then
		__mainObject__.main:SetMode("LIST")
	end
	runCallback("OnFrame")
	reply:write("@@done\n")
	reply:flush()
end
