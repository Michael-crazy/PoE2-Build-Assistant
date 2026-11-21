"""Make a PoB checkout start the in-game assistant shipped next to it (U01).

The release package (R02) puts the assistant in `PoB/assistant-app/`, next to PoB's
executable; the U01 repository layout had it in `assistant/` next to `PoB/`. On start,
PoB spawns `Exiled Exchange 2.exe --pob-pid=<PoB pid>`; the
assistant keeps a single instance and quits after that PoB exits. Running
the script again replaces the hook, so it can be replayed on a new PoB.
"""

import argparse
from pathlib import Path

ANCHOR = "\n\tif not self.devMode and not firstRunFile then\n"
BEGIN = "\t-- PoE2 assistant hook (ops/hook_pob_assistant.py)\n"
END = "\t-- end PoE2 assistant hook\n"
HOOK = BEGIN + """\tdo
\t\t-- Release layout: PoB/assistant-app; repository layout: PoB/runtime/../../assistant.
\t\tlocal assistant = GetRuntimePath() .. "/assistant-app/Exiled Exchange 2.exe"
\t\tlocal file = io.open(assistant, "rb")
\t\tif not file then
\t\t\tassistant = GetRuntimePath() .. "/../../assistant/Exiled Exchange 2.exe"
\t\t\tfile = io.open(assistant, "rb")
\t\tend
\t\tif file then
\t\t\tfile:close()
\t\t\tlocal ffi = require("ffi")
\t\t\tffi.cdef("unsigned long GetCurrentProcessId(void);")
\t\t\tSpawnProcess(assistant, "--pob-pid=" .. tonumber(ffi.C.GetCurrentProcessId()))
\t\tend
\tend
""" + END

# The hook as the U01 commit has it (repository layout only). The legacy install
# scripts must still reproduce that commit exactly (ops/rebase_check.py replay),
# so ops/pob_branch.py installs this text; packaging installs HOOK above.
U01_HOOK = BEGIN + """	do
		local assistant = GetRuntimePath() .. "/../../assistant/Exiled Exchange 2.exe"
		local file = io.open(assistant, "rb")
		if file then
			file:close()
			local ffi = require("ffi")
			ffi.cdef("unsigned long GetCurrentProcessId(void);")
			SpawnProcess(assistant, "--pob-pid=" .. tonumber(ffi.C.GetCurrentProcessId()))
		end
	end
""" + END


def hook(source, text=HOOK):
    if BEGIN in source:
        start = source.index(BEGIN)
        source = source[:start] + source[source.index(END) + len(END):]
    if source.count(ANCHOR) != 1:
        raise ValueError("Expected one update-check block in launch:OnInit")
    return source.replace(ANCHOR, "\n" + text + ANCHOR[1:], 1)


def install(pob, text=HOOK):
    launch = Path(pob) / "src/Launch.lua"
    if not launch.is_file():  # release layout (R02): the scripts sit next to the executable
        launch = Path(pob) / "Launch.lua"
    original = launch.read_bytes()
    hooked = hook(original.decode("utf-8").replace("\r\n", "\n"), text)
    if b"\r\n" in original:
        hooked = hooked.replace("\n", "\r\n")
    launch.write_bytes(hooked.encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pob", type=Path, help="PoB directory containing src/Launch.lua (or Launch.lua, release layout)")
    install(parser.parse_args().pob)


if __name__ == "__main__":
    main()
