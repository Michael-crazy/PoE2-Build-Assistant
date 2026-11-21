-- V10 headless count of what PoB actually draws: every string that reaches DrawString while each
-- build view (sidebar, Tree, Skills, Items, Calcs, Config, Party, Import), each Compare sub-view
-- (with a second build loaded as comparison, including the Compare Power Report), the Trader
-- popup and its "Query Options" (Find best) popup are drawn for one frame, plus the drop-down
-- lists of those popups. English lines are sorted by cause:
--   a_unhooked  the drawn text is English but our lookup (uiText.draw, which now includes the
--               sidebar/calcs label table) has Chinese for it: the draw path has no lookup
--   c_term      a game term the PoE2DB (编年史) tables cover but the path does not look up
--               (passive name, mod line or trade mod template, base/unique/gem name)
--   e_name      item, build or set names (rare random names, user names): not translated
--   d_joined    no table hit and contains digits or '#': runtime-joined text with no rule
--   b_missing   no table hit at all (no candidate source)
-- Run with cwd = <PoB tree>/src under LuaJIT, POE2_ASSISTANT_LOCALE=zh-CN. Globals from the caller:
-- CHECK_BUILDS (build XML paths; the first one is the main build, the second the comparison
-- build), CHECK_OUT (JSON report). Builds are read only.
local stderr = io.stderr
print = function(...)
	local parts = { }
	for i = 1, select("#", ...) do parts[i] = tostring(select(i, ...)) end
	stderr:write(table.concat(parts, "\t"), "\n")
end
io.read = function() error("unexpected interactive input") end

-- Record below any DrawString wrapper PoB installs: hook the engine function right after the
-- SimpleGraphic stubs are defined, before Launch.lua runs.
local current
local drawn = { }
local function record(text)
	if current and type(text) == "string" then
		drawn[current] = drawn[current] or { }
		drawn[current][text] = true
	end
end
local realDofile = dofile
dofile = function(path, ...)
	local results = { realDofile(path, ...) }
	if path == "_SimpleGraphic.def.lua" then
		local raw = DrawString
		DrawString = function(x, y, align, height, font, text, ...)
			record(text)
			return raw(x, y, align, height, font, text, ...)
		end
	end
	return unpack(results)
end
realDofile("HeadlessWrapper.lua")
dofile = realDofile
assert(build and not __mainObject__.promptMsg, "engine startup failed")

local json = require("dkjson")
local uiText = LoadModule("Modules/AssistantUiText")
local terms = LoadModule("Modules/AssistantTerms")
local calcLabel = LoadModule("Modules/AssistantCalcLabels")

local function frame(name)
	current = name
	local ok, err = pcall(runCallback, "OnFrame")
	current = nil
	if not ok then
		print(name .. " frame failed: " .. tostring(err))
	end
end

-- Names that are user content or random (not translatable).
local names = { }
local nodesByName = { }
local function addName(text)
	if type(text) == "string" and text ~= "" then
		names[text] = true
	end
end

local function strip(text)
	return (text:gsub("%^x%x%x%x%x%x%x", ""):gsub("%^%d", ""))
end
local ALLOWED = { DPS = true, EHP = true, PoB = true, PoE = true, BD = true, XML = true, URL = true, III = true }
local function englishWords(text)
	local count = 0
	for word in text:gmatch("%a%a%a+") do
		if not ALLOWED[word] then
			count = count + 1
		end
	end
	return count
end
local function hasCjk(text)
	return text:find("[\228-\233][\128-\191][\128-\191]") ~= nil
end

-- Would any of our tables translate this text if the path looked it up?
local function tableHit(text)
	if uiText.draw(text) ~= text then
		return true
	end
	local plain = strip(text):match("^%s*(.-):?%s*$")
	local label = calcLabel(plain)
	return label ~= nil and label ~= plain
end
local function termHit(text)
	local plain = strip(text):match("^%s*(.-)%s*$")
	local node = nodesByName[plain]
	if node and terms.nodeName(node) ~= plain then
		return true
	end
	if terms.modLine(text) ~= text then
		return true
	end
	if terms.tradeModText and terms.tradeModText(plain) ~= plain then
		return true
	end
	for _, f in ipairs({ terms.baseName, terms.uniqueName, terms.gemNameText, terms.skillLabel }) do
		if f and f(plain) ~= plain then
			return true
		end
	end
	return false
end
local function cause(text)
	local plain = strip(text):match("^%s*(.-)%s*$")
	if names[plain] or names[text] then
		return "e_name"
	end
	if tableHit(text) then
		return "a_unhooked"
	end
	if termHit(text) then
		return "c_term"
	end
	if plain:find("[%d#]") then
		return "d_joined"
	end
	return "b_missing"
end

local report = { builds = { }, areas = { } }
local function addArea(name, texts, translate)
	local a = report.areas[name] or { lines = 0, english = 0, mixed = 0, causes = { }, englishLines = { }, mixedLines = { } }
	report.areas[name] = a
	for text in pairs(texts) do
		if translate then
			text = uiText.draw(text)
		end
		for line in (text .. "\n"):gmatch("([^\n]*)\n") do
			local plain = strip(line):match("^%s*(.-)%s*$")
			if plain ~= "" and plain:match("%a") and not a.englishLines[plain] and not a.mixedLines[plain] then
				a.lines = a.lines + 1
				if englishWords(plain) > 0 then
					if hasCjk(plain) then
						a.mixed = a.mixed + 1
						a.mixedLines[plain] = "mixed"
					else
						a.english = a.english + 1
						local c = cause(line)
						a.causes[c] = (a.causes[c] or 0) + 1
						a.englishLines[plain] = c
					end
				end
			end
		end
	end
end
-- Drop-down lists of the controls of a popup or tab, as DropDownControl draws them.
local function listTexts(control, out, seen)
	if type(control) ~= "table" or seen[control] then
		return out
	end
	seen[control] = true
	if type(control.list) == "table" then
		for _, value in ipairs(control.list) do
			local label = type(value) == "table" and value.label or value
			if type(label) == "string" then
				out[label] = true
			end
		end
	end
	if type(control.controls) == "table" then
		for _, child in pairs(control.controls) do
			listTexts(child, out, seen)
		end
	end
	return out
end

local function readFile(path)
	local file = assert(io.open(path, "rb"))
	local text = file:read("*a")
	file:close()
	return text
end

local mainPath, comparePath = CHECK_BUILDS[1], CHECK_BUILDS[2] or CHECK_BUILDS[1]
loadBuildFromXML(readFile(mainPath), mainPath)
runCallback("OnFrame")
report.builds = { mainPath, comparePath }
for _, item in pairs(build.itemsTab.items) do
	addName(item.name)
	addName(item.title)
	if item.title and item.baseName then
		addName(item.title .. ", " .. item.baseName)
	end
end
addName(build.buildName)
for _, set in pairs(build.itemsTab.itemSets) do addName(set.title) end
for _, spec in ipairs(build.treeTab.specList) do addName(spec.title) end
for _, node in pairs(build.spec.tree.nodes) do
	if type(node.dn) == "string" then
		nodesByName[node.dn] = nodesByName[node.dn] or node
	end
end

-- Sidebar: drawn on every view; take it from the Notes view, whose own text is the user's.
build.viewMode = "NOTES"
frame("sidebar")
local sidebar = drawn.sidebar or { }
for _, view in ipairs({ "TREE", "SKILLS", "ITEMS", "CALCS", "CONFIG", "PARTY", "IMPORT" }) do
	build.viewMode = view
	frame(view:lower())
	for text in pairs(drawn[view:lower()] or { }) do
		if sidebar[text] then
			drawn[view:lower()][text] = nil
		end
	end
end

-- Compare tab with the second build as comparison.
local compareTab = build.compareTab
local okImport, imported = pcall(compareTab.ImportBuild, compareTab, readFile(comparePath), "Compare")
if okImport and imported then
	local entry = compareTab.compareEntries[compareTab.activeCompareIndex]
	for _, item in pairs(entry.itemsTab and entry.itemsTab.items or { }) do
		addName(item.name)
		addName(item.title)
	end
	addName("Compare")
	build.viewMode = "COMPARE"
	for _, mode in ipairs({ "SUMMARY", "TREE", "SKILLS", "ITEMS", "CALCS", "CONFIG" }) do
		compareTab.compareViewMode = mode
		frame("compare " .. mode:lower())
		frame("compare " .. mode:lower())
	end
	-- Power report: pick the first metric and run it to the end.
	compareTab.compareViewMode = "SUMMARY"
	local select = compareTab.controls.comparePowerStatSelect
	select:SetSel(2)
	for _ = 1, 400 do
		frame("compare power report")
		if compareTab.comparePowerResults and not compareTab.comparePowerCoroutine then
			break
		end
	end
	frame("compare power report")
	frame("compare power report")
	for text in pairs(drawn["compare power report"] or { }) do
		if (drawn["compare summary"] or { })[text] or sidebar[text] then
			drawn["compare power report"][text] = nil
		end
	end
	local lists = listTexts(compareTab, { }, { })
	drawn["compare drop-downs"] = lists
else
	print("compare import failed: " .. tostring(imported))
end
for name, texts in pairs(drawn) do
	if name:match("^compare") and name ~= "compare drop-downs" then
		for text in pairs(texts) do
			if sidebar[text] then
				texts[text] = nil
			end
		end
	end
end

-- Trader popup and its Query Options (Find best) popup for Weapon 1.
build.viewMode = "ITEMS"
local tradeQuery = build.itemsTab.tradeQuery
local okTrader, errTrader = pcall(tradeQuery.PriceItem, tradeQuery)
if okTrader then
	frame("trader")
	drawn["trader drop-downs"] = listTexts(main.popups[1], { }, { })
	local generator = tradeQuery.tradeQueryGenerator
	if not generator.modData then
		local okMods, errMods = pcall(generator.InitMods, generator)
		if not okMods then print("InitMods failed: " .. tostring(errMods)) end
	end
	local slot = build.itemsTab.slots["Weapon 1"]
	local context = { slotTbl = { slotName = "Weapon 1" }, controls = tradeQuery.controls, row_idx = 1 }
	local okQuery, errQuery = pcall(generator.RequestQuery, generator, slot, context, { }, function() end)
	if okQuery then
		frame("trader query options")
		drawn["trader query options drop-downs"] = listTexts(main.popups[1], { }, { })
		main:ClosePopup()
	else
		print("query options failed: " .. tostring(errQuery))
	end
	main:ClosePopup()
else
	print("trader failed: " .. tostring(errTrader))
end
for name, texts in pairs(drawn) do
	if name:match("^trader") and not name:match("drop%-downs$") then
		for text in pairs(texts) do
			if sidebar[text] or (drawn.items or { })[text] then
				texts[text] = nil
			end
		end
	end
end

for name, texts in pairs(drawn) do
	-- Drop-down items go through uiText.draw in DropDownControl:Draw.
	addArea(name, texts, name:match("drop%-downs$") ~= nil)
end

-- Lists sorted for reading.
for _, a in pairs(report.areas) do
	for _, field in ipairs({ "englishLines", "mixedLines" }) do
		local list = { }
		for line, c in pairs(a[field]) do
			list[#list + 1] = { line = line, cause = c }
		end
		table.sort(list, function(x, y) return x.cause < y.cause or (x.cause == y.cause and x.line < y.line) end)
		a[field] = list
	end
end
local out = assert(io.open(CHECK_OUT, "wb"))
out:write(json.encode(report, { indent = true }))
out:close()
