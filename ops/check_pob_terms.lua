-- P03 headless check: every Chinese line the display layer produces carries exactly the
-- numbers of PoB's English line. Run with cwd = <PoB tree>/src under LuaJIT, with
-- POE2_ASSISTANT_LOCALE=zh-CN. Globals set by the caller: CHECK_BUILDS (list of build XML
-- paths), CHECK_OUT (report path). The report is JSON; failures list every mismatching line.
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
local terms = LoadModule("Modules/AssistantTerms")
assert(terms.enabled, "set POE2_ASSISTANT_LOCALE=zh-CN")

local function strip(text)
	return (text:gsub("%^x%x%x%x%x%x%x", ""):gsub("%^%d", ""))
end

-- Numbers as shown: signed values and ranges, '+' dropped (a shown '+' never changes a value).
local function shown(text)
	local values = { }
	for _, value in ipairs(terms.lineValues(strip(text))) do
		values[#values + 1] = (value:gsub("^%+", ""):gsub("%(%+", "("):gsub("%-%+", "-"))
	end
	table.sort(values)
	return table.concat(values, " ")
end

local report = { builds = { }, failures = { }, word_numbers = { } }

local function new_counter()
	return { lines = 0, localized = 0, names = 0, names_localized = 0 }
end

-- English number words the Chinese text writes as digits ("eight seconds" -> "8 秒").
local WORDS = { zero = "0", a = "1", an = "1", one = "1", two = "2", three = "3", four = "4", five = "5",
	six = "6", seven = "7", eight = "8", nine = "9", ten = "10", twice = "2", once = "1" }

-- Every English value appears in the Chinese line; any extra Chinese number is one of the
-- English number words.
local function sameNumbers(english, chinese)
	if shown(english) == shown(chinese) then
		return true
	end
	local words = { }
	for word in strip(english):lower():gmatch("%a+") do
		if WORDS[word] then
			words[#words + 1] = WORDS[word]
		end
	end
	local pool = { }
	for v in shown(chinese):gmatch("%S+") do pool[#pool + 1] = v end
	local function take(list, v)
		for i, p in ipairs(list) do
			if p == v then
				table.remove(list, i)
				return true
			end
		end
	end
	for v in shown(english):gmatch("%S+") do
		if not take(pool, v) then
			return false
		end
	end
	for _, v in ipairs(pool) do
		if not take(words, v) then
			return false
		end
	end
	return true
end

local function checkLine(counter, where, english, chinese)
	counter.lines = counter.lines + 1
	if chinese == english then
		if counter.english then
			table.insert(counter.english, english)
		end
		return
	end
	counter.localized = counter.localized + 1
	if shown(english) ~= shown(chinese) then
		counter.word_numbers = (counter.word_numbers or 0) + 1
		table.insert(report.word_numbers, { where = where, en = english, zh = chinese })
	end
	if not sameNumbers(english, chinese) then
		table.insert(report.failures, { where = where, en = english, zh = chinese, en_values = shown(english), zh_values = shown(chinese) })
	end
end

local function checkName(counter, english, chinese)
	counter.names = counter.names + 1
	if chinese ~= english then
		counter.names_localized = counter.names_localized + 1
	elseif counter.english_names then
		table.insert(counter.english_names, english)
	end
end

local function checkNode(counter, node, where)
	if not node.dn or node.type == "ClassStart" then
		return
	end
	checkName(counter, node.dn, terms.nodeName(node))
	for i, line in ipairs(node.sd or { }) do
		checkLine(counter, where .. " node " .. node.id .. " #" .. i, line, terms.nodeLine(node, i, line))
	end
end

local function checkItem(counter, item, where, dbMode)
	checkName(counter, item.name, terms.itemName(item))
	for _, list in ipairs{ item.enchantModLines, item.runeModLines, item.implicitModLines, item.explicitModLines } do
		for _, modLine in ipairs(list or { }) do
			local line = itemLib.formatModLine(modLine, dbMode)
			if line then
				checkLine(counter, where .. " " .. item.name, line, terms.modLine(line, item))
			end
		end
	end
end

for _, path in ipairs(CHECK_BUILDS) do
	local file = assert(io.open(path, "rb"))
	local text = file:read("*a")
	file:close()
	loadBuildFromXML(text, path)
	local entry = { build = path, tree = new_counter(), items = new_counter(), gems = new_counter() }
	-- Builds list what stays English (gaps for the report); the full tree and DB only count.
	for _, c in ipairs{ entry.tree, entry.items, entry.gems } do
		c.english_names, c.english = { }, { }
	end
	for _, node in pairs(build.spec.allocNodes) do
		checkNode(entry.tree, node, "alloc")
	end
	for _, item in pairs(build.itemsTab.items) do
		checkItem(entry.items, item, "item", false)
	end
	for _, group in ipairs(build.skillsTab.socketGroupList) do
		for _, gem in ipairs(group.gemList) do
			if gem.gemData then
				checkName(entry.gems, gem.gemData.name, terms.gemName(gem.gemData))
			end
		end
		if group.displayLabel then
			checkName(entry.gems, group.displayLabel, terms.skillLabel(group.displayLabel))
		end
	end
	entry.allocated_nodes = 0
	for _ in pairs(build.spec.allocNodes) do entry.allocated_nodes = entry.allocated_nodes + 1 end
	table.insert(report.builds, entry)
end

-- The whole tree as the last build has it, and every unique in the item database (ranges).
local tree, uniques = new_counter(), new_counter()
for _, node in pairs(build.spec.nodes) do
	checkNode(tree, node, "tree")
end
for _, typeList in pairs(data.uniques) do
	for _, raw in pairs(typeList) do
		local item = new("Item"):Item(raw, "UNIQUE", true)
		if item.base then
			checkItem(uniques, item, "uniqueDB", true)
		end
	end
end
report.tree, report.unique_db = tree, uniques
report.failure_count = #report.failures

local out = assert(io.open(CHECK_OUT, "wb"))
out:write(json.encode(report, { indent = true }))
out:close()
