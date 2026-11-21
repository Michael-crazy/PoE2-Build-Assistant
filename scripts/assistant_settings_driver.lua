-- Test helper for scripts/test_assistant_settings.py: a headless PoB from our
-- branch with the Options popup open. Run with cwd = <engine>/src and
-- POE2_ASSISTANT_DATA_DIR set:  luajit assistant_settings_driver.lua
-- One command per stdin line; each answers one JSON line on stdout:
--   open                 open Options -> {"values": {id: value|null}, "shown": [ids]}
--   set <id> <json>      set a checkbox / drop-down / hotkey / number box value (a string for the box text)
--   press <id> <key> [ctrl] [shift] [alt]   click a hotkey button and press keys
--   values               the group's current values
--   status               the status line text (one frame)
--   save | cancel        press the popup's button
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
local held = { }
IsKeyDown = function(key) return held[key] or false end

local function answer(value)
	reply:write(dkjson.encode(value), "\n")
	reply:flush()
end

local function controls()
	return main.popups[1] and main.popups[1].controls or { }
end

local function values()
	local result, shown = { }, { }
	for id, control in pairs(controls()) do
		local setting = id:match("^assistant_(%w+)$")
		if setting then
			shown[#shown + 1] = setting
			local value
			if control.list then
				value = control:GetSelValueByKey("value")
			elseif control.isNumeric then -- number box (M08b): empty = 0
				value = tonumber(control.buf) or 0
			elseif control.isHotkey then
				value = control.hotkey
			else
				value = control.state and true or false
			end
			result[setting] = value == nil and dkjson.null or value
		end
	end
	table.sort(shown)
	return { values = result, shown = shown }
end

for line in io.lines() do
	local cmd, rest = line:match("^(%S+)%s*(.*)$")
	if cmd == "open" then
		main:OpenOptionsPopup()
		answer(values())
	elseif cmd == "set" then
		local id, json = rest:match("^(%S+) (.+)$")
		local control = controls()["assistant_" .. id]
		local value = dkjson.decode(json)
		if control.list then
			control:SelByValue(value, "value")
		elseif control.isNumeric then
			control:SetText(tostring(value))
		elseif control.isHotkey then
			control.hotkey = value
		else
			control.state = value
		end
		answer(values())
	elseif cmd == "press" then
		local id, key, mods = rest:match("^(%S+) (%S+)%s*(.*)$")
		local control = controls()["assistant_" .. id]
		held = { }
		for mod in mods:gmatch("%S+") do held[mod:upper()] = true end
		local selected = control.onClick() == control -- a click starts capturing
		local released = control:OnKeyUp("CTRL") == control -- releasing a modifier keeps capturing
		local result = control:OnKeyDown(key)
		held = { }
		answer({ capturing = control.capturing and true or false, keepsFocus = selected and released and result == control,
			hotkey = control.hotkey or dkjson.null })
	elseif cmd == "values" then
		answer(values())
	elseif cmd == "market" then
		-- M09b: click "打开市集"; the bridge answer is `rest` (JSON body, or "" for a connection error).
		local sent = { }
		launch.DownloadPage = function(_, url, callback, params)
			sent.url, sent.header = url, params and params.header
			if rest == "" then
				callback(nil, "Couldn't connect to server")
			else
				callback({ body = rest })
			end
		end
		controls().assistantMarket.onClick()
		answer({ url = sent.url or dkjson.null, header = sent.header or dkjson.null,
			message = controls().assistantMarketResult:GetProperty("label") })
	elseif cmd == "status" then
		answer({ text = controls().assistantStatus:GetProperty("label") })
	elseif cmd == "save" then
		controls().save:Click()
		answer({ open = main.popups[1] ~= nil })
	elseif cmd == "cancel" then
		controls().cancel:Click()
		answer({ open = main.popups[1] ~= nil })
	end
end
