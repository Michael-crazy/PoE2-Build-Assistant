-- Run inside the pinned PoB Lua environment with an already loaded build.
-- Keep conversion in upstream Modules.BuildExportPoE2; this is only an adapter.
local upstream = require('Modules.BuildExportPoE2')
local M = {}

function M.write(build, path, metadata, selection)
    assert(type(path) == 'string' and path:sub(-6) == '.build', 'output must end in .build')
    assert(selection and selection.specIndex and selection.skillSetId and selection.itemSetId,
        'select a tree, skill set and item set explicitly')
    local spec, skills, items = upstream.ResolveSelection(build, selection)
    assert(spec and skills and items, 'selected tree, skill set or item set does not exist')
    local json, err = upstream.Export(build, metadata, selection)
    if not json then return nil, err end
    -- Caller supplies an existing output directory. Never use the game default path.
    local file
    file, err = io.open(path, 'w')
    if not file then return nil, err end
    local ok
    ok, err = file:write(json)
    local closed, closeErr = file:close()
    if not ok then return nil, err end
    if not closed then return nil, closeErr end
    return path
end

return M
