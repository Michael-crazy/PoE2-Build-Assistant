-- D02 headless dump: every gem tooltip as GemTooltip.AddGemTooltip draws it (through the real
-- Tooltip class, so the P10b fallback runs too). Run with cwd = <PoB tree>/src under LuaJIT;
-- POE2_ASSISTANT_LOCALE decides the language. Globals set by the caller: CHECK_OUT (JSON path),
-- CHECK_LEVEL, CHECK_QUALITY. Output: { [mode] = { [gemId] = { lines... } } }, modes "skills"
-- (skills tab / gem dropdown hover) and "tree" (passive tree: level ranges, quality ranges).
local stderr = io.stderr
print = function(...)
	local parts = { }
	for i = 1, select("#", ...) do parts[i] = tostring(select(i, ...)) end
	stderr:write(table.concat(parts, "\t"), "\n")
end
io.read = function() error("unexpected interactive input") end
dofile("HeadlessWrapper.lua")
assert(build and not __mainObject__.promptMsg, "engine startup failed")

local json = require("dkjson")
local gemTooltip = LoadModule("Classes/GemTooltip")
local uiText = LoadModule("Modules/AssistantUiText")

local function tooltipLines(gemData, options)
	local tooltip = new("Tooltip"):Tooltip()
	-- One entry per AddLine call, as the tooltip draws it (P10b runs in AddLine), before wrapping.
	local out = { }
	local classAddLine = tooltip.AddLine
	tooltip.AddLine = function(self, size, text, ...)
		if type(text) == "string" then
			local drawn = { }
			for line in (uiText.draw(text) .. "\n"):gmatch("([^\n]*)\n") do
				drawn[#drawn + 1] = uiText.draw(line)
			end
			out[#out + 1] = table.concat(drawn, "\n")
		end
		return classAddLine(self, size, text, ...)
	end
	local gemInstance = {
		level = math.min(CHECK_LEVEL, gemData.naturalMaxLevel or CHECK_LEVEL),
		quality = CHECK_QUALITY, count = 1, enabled = true, enableGlobal1 = true, enableGlobal2 = true,
		gemId = gemData.id, nameSpec = gemData.name, skillId = gemData.grantedEffectId,
		gemData = gemData, corruptLevel = 0, corrupted = false,
	}
	local ok, err = pcall(gemTooltip.AddGemTooltip, tooltip, build, gemInstance, options)
	if not ok then
		return { "ERROR " .. tostring(err) }
	end
	return out
end

local report = { skills = { }, tree = { } }
for gemId, gemData in pairs(data.gems) do
	report.skills[gemId] = tooltipLines(gemData, { })
	report.tree[gemId] = tooltipLines(gemData, { levelRange = true, includeQualityRange = true })
end
local file = assert(io.open(CHECK_OUT, "w"))
file:write(json.encode(report))
file:close()
