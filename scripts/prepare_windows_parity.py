"""Generate isolated PoB XML copies for manual Windows trial comparison."""

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def prepare(fixture, output):
    expected = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))
    inputs = {name: (fixture / name).read_bytes() for name in ("build.xml", "wand.txt", "bow.txt")}
    for name, content in inputs.items():
        if hashlib.sha256(content).hexdigest() != expected["inputs_sha256"][name]:
            raise ValueError(f"Fixture hash mismatch: {name}")

    output.mkdir(parents=True, exist_ok=True)
    (output / "P02-Parity-Pristine.xml").write_bytes(inputs["build.xml"])
    for name in ("wand", "bow"):
        build = ET.fromstring(inputs["build.xml"])
        items = build.find("Items")
        item_id = str(max(int(item.attrib["id"]) for item in items.findall("Item")) + 1)
        ET.SubElement(items, "Item", id=item_id).text = "\n" + inputs[f"{name}.txt"].decode("utf-8")
        case = expected["cases"][name]
        active_set = items.find(f"ItemSet[@id='{items.attrib['activeItemSet']}']")
        active_set.find(f"Slot[@name='{case['slot']}']").set("itemId", item_id)
        ET.ElementTree(build).write(output / f"P02-Parity-{name}.xml", encoding="utf-8",
                                    xml_declaration=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.fixture, args.output)
