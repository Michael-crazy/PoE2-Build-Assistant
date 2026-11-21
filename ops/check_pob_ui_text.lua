-- P10b headless count: how much English is left in the interface areas the user reported
-- (warnings, calc breakdowns, item and flask tooltips, Config tab labels and tooltips, passive
-- tooltips, Items tab controls and the Craft Item popup). Run with cwd = <PoB tree>/src under
-- LuaJIT, POE2_ASSISTANT_LOCALE=zh-CN. Globals from the caller: CHECK_BUILDS (build XML paths),
-- CHECK_OUT (JSON report). Collects text as PoB would draw it in the tree it runs in, so running
-- it on the tree before and after a change gives the before/after counts. Builds are read only.
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
local uiText = LoadModule("Modules/AssistantUiText")
local calcLabel = LoadModule("Modules/AssistantCalcLabels")
-- Text drawn through uiText.draw only from P10b on (tooltip lines, breakdown cells).
local p10b = uiText.fallback ~= nil
local function cell(text)
	return p10b and uiText.draw(text) or text
end

local function strip(text)
	return (text:gsub("%^x%x%x%x%x%x%x", ""):gsub("%^%d", ""))
end
-- English: no CJK character and an English word of 3+ letters. Mixed: CJK plus such a word.
local ALLOWED = { DPS = true, EHP = true, PoB = true, BD = true, XML = true, URL = true }
local function englishWords(text)
	local count = 0
	for word in text:gmatch("%a%a%a+") do
		if not ALLOWED[word] then
			count = count + 1
		end
	end
	return count
end

local report = { builds = { }, areas = { } }
local function area(name)
	report.areas[name] = report.areas[name] or { lines = 0, english = 0, mixed = 0, englishLines = { }, mixedLines = { } }
	return report.areas[name]
end
local function add(name, text)
	if type(text) ~= "string" then
		return
	end
	for line in (text .. "\n"):gmatch("([^\n]*)\n") do
		local plain = strip(line):match("^%s*(.-)%s*$")
		if plain ~= "" and plain:match("%a") then
			local a = area(name)
			a.lines = a.lines + 1
			local cjk = plain:find("[\228-\233][\128-\191][\128-\191]") ~= nil
			if englishWords(plain) > 0 then
				if cjk then
					a.mixed = a.mixed + 1
					a.mixedLines[plain] = (a.mixedLines[plain] or 0) + 1
				else
					a.english = a.english + 1
					a.englishLines[plain] = (a.englishLines[plain] or 0) + 1
				end
			end
		end
	end
end
local function tooltipLines(name, fill)
	local tooltip = new("Tooltip"):Tooltip()
	local ok, err = pcall(fill, tooltip)
	if not ok then
		print("tooltip failed: " .. tostring(err))
		return
	end
	for _, line in ipairs(tooltip.lines) do
		add(name, line.text)
	end
end
local function controlText(name, control, seen)
	if type(control) ~= "table" or seen[control] then
		return
	end
	seen[control] = true
	for _, key in ipairs({ "label", "title" }) do
		local ok, value = pcall(function() return control.GetProperty and control:GetProperty(key) or control[key] end)
		if ok and type(value) == "string" then
			add(name, uiText.draw(value))
		end
	end
	if type(control.list) == "table" then
		for _, value in ipairs(control.list) do
			local label = type(value) == "table" and value.label or value
			if type(label) == "string" then
				add(name .. " drop-downs", uiText.draw(label))
			end
		end
	end
	if type(control.controls) == "table" then
		for _, child in pairs(control.controls) do
			controlText(name, child, seen)
		end
	end
end

for _, path in ipairs(CHECK_BUILDS) do
	local file = assert(io.open(path, "rb"))
	local text = file:read("*a")
	file:close()
	loadBuildFromXML(text, path)
	runCallback("OnFrame")
	if build.RefreshStatList then
		build:RefreshStatList()
	end
	report.builds[#report.builds + 1] = path

	-- Warnings, drawn into a tooltip as in Build.lua.
	tooltipLines("warnings", function(tooltip)
		for _, line in pairs(build.controls.warnings.lines) do
			tooltip:AddLine(16, line)
		end
	end)

	-- Calc breakdowns of the main actor (text lines, table cells and footers).
	local actor = build.calcsTab.mainEnv.player
	for _, breakdown in pairs(actor.breakdown or { }) do
		if type(breakdown) == "table" then
			local lines = { }
			for _, line in ipairs(breakdown) do
				if type(line) == "string" then
					lines[#lines + 1] = line
				end
			end
			for _, line in ipairs(calcLabel(lines, "lines") or { }) do
				add("breakdown lines", line)
			end
			if breakdown.rowList and breakdown.colList then
				for _, row in ipairs(breakdown.rowList) do
					for _, col in ipairs(breakdown.colList) do
						if type(row[col.key]) == "string" then
							add("breakdown cells", cell(row[col.key]))
						end
					end
				end
			end
			if type(breakdown.footer) == "string" then
				add("breakdown cells", cell(breakdown.footer))
			end
		end
	end

	-- Item and flask tooltips.
	for _, item in pairs(build.itemsTab.items) do
		local kind = (item.base and item.base.flask) and "flask tooltips" or "item tooltips"
		tooltipLines(kind, function(tooltip) build.itemsTab:AddItemTooltip(tooltip, item) end)
	end

	-- Config tab: labels and tooltips of every option control.
	for _, control in pairs(build.configTab.varControls or { }) do
		local ok, label = pcall(function() return control:GetProperty("label") end)
		if ok then
			add("config labels", uiText.draw(label))
		end
		local okTip, tip = pcall(function() return control:GetProperty("tooltipText") end)
		if okTip and type(tip) == "string" and tip ~= "" then
			tooltipLines("config tooltips", function(tooltip) tooltip:AddLine(14, tip) end)
		end
	end

	-- Passive tooltips of the allocated nodes.
	for _, node in pairs(build.spec.allocNodes) do
		tooltipLines("passive tooltips", function(tooltip) build.treeTab.viewer:AddNodeTooltip(tooltip, node, build) end)
	end

	-- Items tab controls (help text, filters, buttons) and the Craft Item popup.
	controlText("items tab", build.itemsTab, { })
	local ok, err = pcall(function() build.itemsTab:CraftItem() end)
	if ok and main.popups and main.popups[1] then
		controlText("craft popup", main.popups[1], { })
		main:ClosePopup()
	elseif not ok then
		print("craft popup failed: " .. tostring(err))
	end
end

-- Lists sorted by count for reading.
for _, a in pairs(report.areas) do
	for _, field in ipairs({ "englishLines", "mixedLines" }) do
		local list = { }
		for line, count in pairs(a[field]) do
			list[#list + 1] = { line = line, count = count }
		end
		table.sort(list, function(x, y) return x.count > y.count or (x.count == y.count and x.line < y.line) end)
		a[field] = list
	end
end
local out = assert(io.open(CHECK_OUT, "wb"))
out:write(json.encode(report, { indent = true }))
out:close()
