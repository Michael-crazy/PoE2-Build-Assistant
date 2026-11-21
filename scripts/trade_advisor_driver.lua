-- Test helper for scripts/test_trade_advisor.py (M05): PoB's Trader with the M05 additions,
-- headless, on a fixture build. Run with cwd = <engine>/src, M05_BUILD = build XML and
-- M05_FETCH = an English fetch answer (scripts/tencent_trade.py output). Prints one JSON object.
local reply = io.stdout
io.output(io.stderr)
print = function(...)
	local parts = { }
	for i = 1, select("#", ...) do parts[i] = tostring(select(i, ...)) end
	io.stderr:write(table.concat(parts, "\t"), "\n")
end

dofile("HeadlessWrapper.lua")
local dkjson = require("dkjson")
local advisor = LoadModule("Modules/AssistantTradeAdvisor")
local out = { }

local function read(path)
	local file = io.open(path, "rb")
	local text = file:read("*a")
	file:close()
	return text
end

loadBuildFromXML(read(os.getenv("M05_BUILD")), "M05")
local calcFunc, baseOutput = build.calcsTab:GetMiscCalculator()

-- 1. Gap filters with the gloves slot emptied
out.gaps = advisor.GapFilters(calcFunc, "Gloves")
out.base = { fire = baseOutput.MissingFireResist, str = baseOutput.Str, reqStr = baseOutput.ReqStr }
out.merged = advisor.MergeRequired({ { tradeId = "pseudo.pseudo_total_fire_resistance", value = 10 } }, out.gaps)

-- 2. Fetched items (the assistant's English answer) through the Trader's own parser
local requests = new("TradeQueryRequests"):TradeQueryRequests()
local body = read(os.getenv("M05_FETCH"))
function launch:DownloadPage(url, callback)
	callback({ header = "HTTP/1.1 200 OK\r\n", body = body })
end
local items
requests:FetchResultBlock("https://example.invalid/fetch", function(result) items = result end)
requests:ProcessQueue()

local trade = build.itemsTab.tradeQuery
trade.pbRealm, trade.pbLeague = "tencent", "奥杜尔秘符"
trade.pbCurrencyConversion.tencent = setmetatable({ timestamp = 0 }, { __index = function()
	return { divine = 1, exalted = 1 / 300, chaos = 1 / 20 }
end })
trade.statSortSelectionList = { { label = "Full DPS", stat = "FullDPS", weightMult = 1.0 }, { label = "Effective Hit Pool", stat = "TotalEHP", weightMult = 0.5 } }
trade.slotTables = { { slotName = "Gloves" } }
-- set up as PriceItem does when the Trader opens
trade.sortModes = { StatValue = "(Highest) Stat Value", StatValuePrice = "Stat Value / Price", Price = "(Lowest) Price", Weight = "(Highest) Weighted Sum" }
for _, key in ipairs(advisor.SORT_ORDER) do
	trade.sortModes[key] = advisor.SORT_MODES[key]
end
trade.tradeQueryGenerator = new("TradeQueryGenerator"):TradeQueryGenerator(trade)
local safe = trade:FilterToSafeItems(items, "Gloves")
-- the fixture has one pair of gloves: three copies at different prices order the value sorts
while #safe < 3 do
	table.insert(safe, copyTable(safe[1]))
end
local prices = { { 1, "divine" }, { 600, "exalted" }, { 5, "chaos" } }
for i, entry in ipairs(safe) do
	entry.amount, entry.currency = prices[(i - 1) % 3 + 1][1], prices[(i - 1) % 3 + 1][2]
end
trade.resultTbl[1] = safe
out.candidates = #safe
out.sorted = { }
for _, key in ipairs(advisor.SORT_ORDER) do
	local sorted, err = trade:SortFetchResults(1, advisor.SORT_MODES[key])
	local rows = { }
	for _, row in ipairs(sorted or { }) do
		local result = safe[row.index]
		local metrics = result.evaluation[1].metrics
		table.insert(rows, { index = row.index, key = row.outputAttr, dps = metrics.dps, ehp = metrics.ehp,
			divines = trade:ConvertCurrencyToDivs(result.currency, result.amount),
			text = advisor.Describe(key, metrics, trade:ConvertCurrencyToDivs(result.currency, result.amount)) })
	end
	out.sorted[key] = { rows = rows, err = err }
end
-- a price without a rate: value sorting falls back like the Trader's own value sort
safe[1].currency = "annul"
local _, err = trade:SortFetchResults(1, advisor.SORT_MODES.DPSPerDivine)
out.missingRate = err
safe[1].currency = "divine"

-- 3. Budget
trade.budget = 10
trade.totalPrice = { [1] = { currency = "exalted", amount = 600 }, [2] = { currency = "divine", amount = 3 } }
out.remainingOther = advisor.RemainingBudget(trade.budget, trade.totalPrice, 2, function(c, a) return trade:ConvertCurrencyToDivs(c, a) end)
out.total = trade:GetTotalPriceString()

reply:write(dkjson.encode(out), "\n")
reply:flush()
