"""Make a PoB checkout start the in-game assistant shipped next to it (U01).

The package puts PoB in `PoB/` and the assistant in `assistant/`. On start,
PoB spawns `assistant/Exiled Exchange 2.exe --pob-pid=<PoB pid>`; the
assistant keeps a single instance and quits after that PoB exits. Running
the script again replaces the hook, so it can be replayed on a new PoB.
"""

import argparse
from pathlib import Path

ANCHOR = "\n\tif not self.devMode and not firstRunFile then\n"
BEGIN = "\t-- PoE2 assistant hook (ops/hook_pob_assistant.py)\n"
END = "\t-- end PoE2 assistant hook\n"
HOOK = BEGIN + """\tdo
\t\tlocal assistant = GetRuntimePath() .. "/../../assistant/Exiled Exchange 2.exe"
\t\tlocal file = io.open(assistant, "rb")
\t\tif file then
\t\t\tfile:close()
\t\t\tlocal ffi = require("ffi")
\t\t\tffi.cdef("unsigned long GetCurrentProcessId(void);")
\t\t\tSpawnProcess(assistant, "--pob-pid=" .. tonumber(ffi.C.GetCurrentProcessId()))
\t\tend
\tend
""" + END


def hook(source):
    if BEGIN in source:
        start = source.index(BEGIN)
        source = source[:start] + source[source.index(END) + len(END):]
    if source.count(ANCHOR) != 1:
        raise ValueError("Expected one update-check block in launch:OnInit")
    return source.replace(ANCHOR, "\n" + HOOK + ANCHOR[1:], 1)


def install(pob):
    launch = Path(pob) / "src/Launch.lua"
    original = launch.read_bytes()
    hooked = hook(original.decode("utf-8").replace("\r\n", "\n"))
    if b"\r\n" in original:
        hooked = hooked.replace("\n", "\r\n")
    launch.write_bytes(hooked.encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pob", type=Path, help="PoB directory containing src/Launch.lua")
    install(parser.parse_args().pob)


if __name__ == "__main__":
    main()
