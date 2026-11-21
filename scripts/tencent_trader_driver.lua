-- Test helper for scripts/test_tencent_trader.py (M04): PoB's Trader request code from our
-- branch, headless, with launch:DownloadPage answered from a queue. Run with cwd = <engine>/src,
-- POE2_ASSISTANT_DATA_DIR (config.json + assistant-status.json) and M04_FETCH = a JSON file with
-- an English fetch answer (scripts/tencent_trade.py output). Prints one JSON object on stdout.
local reply = io.stdout
io.output(io.stderr)
print = function(...)
	local parts = { }
	for i = 1, select("#", ...) do parts[i] = tostring(select(i, ...)) end
	io.stderr:write(table.concat(parts, "\t"), "\n")
end

dofile("HeadlessWrapper.lua")
local dkjson = require("dkjson")
local out = { }

local calls, answers = { }, { }
local OK = "HTTP/1.1 200 OK\r\nX-Rate-Limit-Policy: trade-search-request-limit\r\nX-Rate-Limit-Rules: Account\r\nX-Rate-Limit-Account: 3:5:60\r\nX-Rate-Limit-Account-State: 1:5:0\r\n"
function launch:DownloadPage(url, callback, params)
	params = params or { }
	calls[#calls + 1] = { url = url, header = params.header, body = params.body }
	local answer = table.remove(answers, 1) or { body = "{}" }
	callback({ header = answer.header or OK, body = answer.body }, answer.errMsg)
end

local function run(requests, done)
	-- a fresh limiter per scenario: the queued answers carry rate limit states
	requests.rateLimiter = new("TradeQueryRateLimiter"):TradeQueryRateLimiter()
	for _ = 1, 50 do
		if done() then
			return true
		end
		requests:ProcessQueue()
	end
	return done()
end

local fetchFile = io.open(os.getenv("M04_FETCH"), "rb")
local fetchBody = fetchFile:read("*a")
fetchFile:close()
local query = [[{"query":{"status":{"option":"online"},"stats":[{"type":"weight","value":{"min":1},"filters":[]}]},"sort":{"statgroup.0":"desc"}}]]

-- 1. Tencent search + fetch through the assistant
local requests = new("TradeQueryRequests"):TradeQueryRequests()
requests.maxFetchPerSearch = 10 -- one fetch block; the queued answer holds every item
local ids = { }
for i, entry in ipairs(dkjson.decode(fetchBody).result) do
	ids[i] = entry.id
end
answers = { { body = dkjson.encode({ id = "Q1", result = ids, total = #ids }) }, { body = fetchBody } }
local items, err
run(requests, function() return items or err end)
requests:SearchWithQuery("tencent", "奥杜尔秘符", query, function(result, errMsg) items, err = result or false, errMsg end)
run(requests, function() return items ~= nil end)
out.tencent = { calls = calls, err = err, items = { } }
for _, entry in ipairs(items or { }) do
	local item = new("Item"):Item(entry.item_string)
	table.insert(out.tencent.items, { base = item.baseName, rarity = item.rarity, amount = entry.amount, currency = entry.currency,
		weight = entry.weight, trader = entry.trader, mods = #item.explicitModLines, text = entry.item_string })
end

-- 2. International search: OAuth header, www.pathofexile.com, unchanged
calls, items, err = { }, nil, nil
main.api = main.api or { }
main.api.authToken = "test-token"
answers = { { body = dkjson.encode({ id = "Q2", result = { "x1" }, total = 1 }) }, { body = [[{"result":[]}]] } }
requests:SearchWithQuery("poe2", "Standard", query, function(result, errMsg) items, err = result or false, errMsg end)
run(requests, function() return items ~= nil end)
out.international = { calls = calls, err = err }
main.api.authToken = nil

-- 3. Login missing on the Tencent site (assistant answers 401 with its message)
calls, items, err = { }, nil, nil
answers = { { header = "HTTP/1.1 401 Unauthorized\r\n", errMsg = "Response code: 401", body = [[{"error":{"code":0,"message":"国服市集未登录或登录已过期"}}]] } }
requests:SearchWithQuery("tencent", "奥杜尔秘符", query, function(result, errMsg) items, err = result or false, errMsg end)
run(requests, function() return items ~= nil end)
out.login = { err = err }

-- 4. Pasted Tencent link -> search through the assistant; web link building
calls, items, err = { }, nil, nil
local tradeHelpers = require("Classes.TradeHelpers")
-- the headless host has no zlib: links carry the plain query here, base64 as on the site
Deflate = function(text) return text end
Inflate = function(text) return text end
local link = requests:buildUrl("https://poe.game.qq.com/trade2/search", "tencent", "奥杜尔秘符", tradeHelpers.B64GzipEncode([[{"status":{"option":"online"},"stats":[{"type":"and","filters":[]}]}]]))
answers = { { body = dkjson.encode({ id = "Q3", result = { }, total = 0 }) } }
requests:SearchWithURL(link, function(result, errMsg) items, err = result or false, errMsg end)
run(requests, function() return items ~= nil end)
out.link = { link = link, calls = calls, err = err }

-- 5. Leagues from the assistant
calls = { }
answers = { { body = [[{"result":[{"id":"奥杜尔秘符","realm":"poe2"},{"id":"周年庆巅峰挑战（专家）","realm":"poe2"},{"id":"S1","realm":"pc"}]}]] } }
requests:FetchLeagues("tencent", function(leagues, errMsg) out.leagues = { leagues = leagues, err = errMsg, calls = calls } end)

-- 6. Trader: realm list, authorisation, rates and total price
local trade = new("TradeQuery"):TradeQuery({ })
out.trader = { realmIndex = trade.pbRealmIndex }
trade.pbRealm = "poe2"
out.trader.canSearchInternational = trade:CanSearch()
trade.pbRealm, trade.pbLeague = "tencent", "奥杜尔秘符"
out.trader.canSearchTencent = trade:CanSearch()
trade:PullCXData()
out.trader.exalted = trade:ConvertCurrencyToDivs("exalted", 100)
out.trader.chaos = trade:ConvertCurrencyToDivs("chaos", 30)
out.trader.annul = trade:ConvertCurrencyToDivs("annul", 1) or dkjson.null
trade.totalPrice = { { currency = "exalted", amount = 100 }, { currency = "divine", amount = 1 } }
out.trader.total = trade:GetTotalPriceString()
trade.totalPrice = { { currency = "annul", amount = 2 } }
out.trader.totalWithoutRate = trade:GetTotalPriceString()

-- 7. Assistant not running
local status = io.open(os.getenv("POE2_ASSISTANT_DATA_DIR") .. "/apt-data/assistant-status.json", "wb")
status:write([[{"protocol":"assistant-status/1","pid":1,"time":1,"port":41812}]])
status:close()
calls, items, err = { }, nil, nil
requests:SearchWithQuery("tencent", "奥杜尔秘符", query, function(result, errMsg) items, err = result or false, errMsg end)
out.stopped = { err = err, calls = #calls }

reply:write(dkjson.encode(out), "\n")
reply:flush()
