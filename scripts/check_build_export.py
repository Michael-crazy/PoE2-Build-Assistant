"""Replay the real-engine Build Planner export in a disposable PoB copy."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


HARNESS = """
local fixturePath, adapterPath, outputPath = arg[1], arg[2], arg[3]

local function readFile(path)
    local file = assert(io.open(path, 'rb'))
    local contents = file:read('*a')
    file:close()
    return contents
end

local original = dofile
dofile = function(path)
    local result = original(path)
    if path == '_SimpleGraphic.def.lua' then
        LaunchSubScript = function() error('background scripts disabled') end
        OpenURL = function() error('URLs disabled') end
    end
    return result
end
io.read = function() error('unexpected interactive input') end
original('HeadlessWrapper.lua')
assert(build and not __mainObject__.promptMsg, 'engine startup failed')
__mainObject__.DownloadPage = function() error('network disabled') end
__mainObject__.CheckForUpdate = function() error('updates disabled') end
loadBuildFromXML(readFile(fixturePath), 'Export Smoke')
assert(not __mainObject__.promptMsg and not build.abortSave and not build.loadError, 'build load failed')
local exporter = original(adapterPath)
local path, err = exporter.write(build, outputPath, {
    name = 'P06 Fireball', author = 'PoE2 Build Assistant',
    description = 'Real-engine smoke fixture', useGeneratedItemText = true,
}, {specIndex = 1, skillSetId = 1, itemSetId = 1})
assert(path, err)
"""


def check_export(engine, interpreter, adapter, fixture, output):
    pin = "601768bd105869618c3d6581b883e5d7aeec91b2"
    head = subprocess.check_output(["git", "-C", engine, "rev-parse", "HEAD"], text=True)
    if head.strip() != pin:
        raise ValueError(f"Expected PoB source {pin}, found {head.strip()}")
    with tempfile.TemporaryDirectory(prefix="pob-export-") as directory:
        scratch = Path(directory)
        for name in ("src", "runtime"):
            shutil.copytree(engine / name, scratch / name)
        shutil.copy2(engine / "manifest.xml", scratch / "manifest.xml")
        harness = scratch / "export.lua"
        harness.write_text(HARNESS, encoding="utf-8")
        generated = scratch / "fireball.build"
        environment = dict(os.environ, LUA_PATH="../runtime/lua/?.lua;../runtime/lua/?/init.lua;;")
        environment.pop("CI", None)
        subprocess.run(
            [interpreter, harness, fixture, adapter, generated],
            cwd=scratch / "src", env=environment, check=True, timeout=120,
        )
        document = json.loads(generated.read_bytes())
        skill_ids = {entry["id"] for entry in document["skills"]}
        passive_ids = {entry["id"] for entry in document["passives"]}
        slots = {entry["inventory_id"]: entry["additional_text"]
                 for entry in document["inventory_slots"]}
        if (
            document["name"] != "P06 Fireball"
            or "Metadata/Items/Gem/SkillGemFireball" not in skill_ids
            or "ranger596" not in passive_ids
            or "Hallowed Focus" not in slots.get("Offhand1", "")
        ):
            raise ValueError("Export is missing expected Fireball build content")
        with output.open("xb") as destination:
            destination.write(generated.read_bytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "interpreter", "adapter", "fixture", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    check_export(args.engine, args.interpreter, args.adapter, args.fixture, args.output)
