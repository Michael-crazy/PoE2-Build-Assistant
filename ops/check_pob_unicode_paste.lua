-- Run with PoB's LuaJIT and lua-utf8 against the patched EditControl.lua.
local path = assert(arg[1])
local class = {}
local clipboard
function newClass() return class end
function Paste() return clipboard end
function IsKeyDown(key) return key == "CTRL" end
function GetTime() return 0 end
dofile(path)

local function edit(filter, initial)
    local widget = setmetatable({
        buf = initial, caret = #initial + 1, filterPattern = filter,
        IsShown = function() return true end,
        IsEnabled = function() return true end,
        GetMouseOverControl = function() end,
        ScrollCaretIntoView = function() end,
        AddUndoState = function() end,
    }, {__index = class})
    return widget
end

local search = edit("[%c]", "")
clipboard = "天赋搜索"
search:OnKeyDown("v")
assert(search.buf == clipboard and search.caret == #clipboard + 1)

local notes = edit("[%z]", "replace me")
notes.sel = 1
clipboard = "开荒备注\r\n保留第二行"
notes:OnKeyDown("v")
assert(notes.buf == "开荒备注\n保留第二行")

local name = edit('[/:%*%?"<>|%c]', "")
clipboard = "中文配装*"
name:OnKeyDown("v")
assert(name.buf == "中文配装")

local invalid = edit("[%c]", "")
clipboard = "A" .. string.char(255) .. "B"
invalid:OnKeyDown("v")
assert(invalid.buf == "A?B")
print("P07 EditControl clipboard: 4 checks passed")
