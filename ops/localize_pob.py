"""Apply the Simplified Chinese navigation labels to a pinned PoB checkout."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile


CJK_RELEASE_SHA = "b686f3780f7852346aff18ebadb43f25f5fdb468fa1ad515f274977040473fbb"
CJK_SOURCE_PIN = "8cb176392b923627c42879e6af17d27d4806a4a4"
CJK_FONT_FILES = (
    "SimpleGraphic/Fonts/UnicodeFallback.tgf",
    "SimpleGraphic/Fonts/NotoSansCJKtc-Regular.otf",
    "SimpleGraphic/Fonts/NotoSansCJK-LICENSE.txt",
)
LABELS = {
    "back": ("<< Back", "<< 返回"),
    "save": ("Save", "保存"),
    "saveAs": ("Save As", "另存为"),
    "modeImport": ("Import/Export Build", "导入／导出 BD"),
    "modeNotes": ("Notes", "备注"),
    "modeConfig": ("Configuration", "配置"),
    "modeTree": ("Tree", "天赋"),
    "modeSkills": ("Skills", "技能"),
    "modeItems": ("Items", "装备"),
    "modeCalcs": ("Calcs", "计算"),
    "modeParty": ("Party", "队伍"),
    "modeCompare": ("Compare", "对比"),
    "mainSkillLabel": ("^7Main Skill:", "^7主技能："),
}
PAGE_LABELS = {
    "ImportTab": {
        "authenticateButton": ("^7Authorize with Path of Exile", "^7授权流放之路账号"),
        "charImportTree": ("Passive Tree and Jewels", "天赋树和珠宝"),
        "charImportItems": ("Items and Skills", "装备和技能"),
        "sectionCharImport": ("Character Import", "角色导入"),
        "sectionBuild": ("Build Sharing", "BD 分享"),
        "sectionPoE2Export": ("Export to in-game build planner", "导出到游戏内 BD 规划器"),
        "generateCodeLabel": ("^7Generate a code to share this build with other Path of Building users:", "^7生成分享码，与其他 PoB 玩家分享此 BD："),
        "generateCode": ("Generate", "生成"),
        "generateCodeCopy": ("Copy", "复制"),
        "generateCodeByLink": ("Share", "分享"),
        "generateCodeNote": ("^7Note: this code can be very long; you can use 'Share' to shrink it.", "^7分享码过长时，可点击「分享」生成链接。"),
        "importCodeHeader": ("^7To import a build, enter URL or code here:", "^7输入链接或分享码以导入 BD："),
        "poe2ExportOpenFolder": ("Open Folder", "打开文件夹"),
        "importCodeGo": ("Import", "导入"),
        "buildPlannerTreeLabel": ("^7Tree", "^7天赋"),
        "buildPlannerSkillLabel": ("^7Skill", "^7技能"),
        "buildPlannerItemLabel": ("^7Item", "^7装备"),
        "buildPlannerDescLabel": ("^7Description:", "^7说明："),
        "buildPlannerUseGeneratedItemText": ("Generated text for empty item notes", "为无备注装备生成说明"),
        "poe2ExportShowPath": ("Show full path", "显示完整路径"),
        "poe2ExportSave": ("Export Selected Sets", "导出选中方案"),
        "poe2ExportSaveAll": ("Export All Loadouts", "导出全部配置"),
        "poe2ExportDesc": ("^7Save this build as a .build file the in-game build planner can load.",
                          "^7将此 BD 保存为游戏内规划器可读取的 .build 文件。"),
        "poe2ExportDesc2": ("^8Each file holds one passive tree, one skill set and one item set.",
                           "^8每个文件包含一套天赋、技能和装备方案。"),
    },
    "TreeTab": {
        "compareCheck": ("Compare:", "对比："),
        "reset": ("Reset Tree", "重置天赋树"),
        "versionText": ("Version:", "版本："),
        "treeSearch": ("Search", "搜索"),
        "treeHeatMap": ("Show Node Power:", "显示天赋收益："),
    },
    "SkillsTab": {
        "setLabel": ("^7Skill set:", "^7技能方案："),
        "setManage": ("Manage...", "管理…"),
        "optionSection": ("Gem Options", "宝石选项"),
        "sortGemsByDPS": ("Sort gems by DPS:", "按 DPS 排序："),
        "defaultLevelLabel": ("^7Default gem level:", "^7默认宝石等级："),
        "defaultQualityLabel": ("^7Default gem quality:", "^7默认宝石品质："),
        "gemNameHeader": ("^7Gem name:", "^7宝石名称："),
        "gemLevelHeader": ("^7Level:", "^7等级："),
        "gemQualityHeader": ("^7Quality:", "^7品质："),
        "showSupportGemTypesLabel": ("^7Show support gems:", "^7显示辅助宝石："),
        "showLegacyGems": ("^7Show legacy gems:", "^7显示旧版宝石："),
        "groupEnabled": ("Enabled:", "启用："),
        "includeInFullDPS": ("Include in Full DPS:", "计入总 DPS："),
        "gemEnableHeader": ("^7Enabled:", "^7启用："),
        "gemCountHeader": ("^7Count:", "^7数量："),
        "gemCorruptHeader": ("^7Corrupt:", "^7腐化："),
    },
    "ItemsTab": {
        "setLabel": ("^7Item set:", "^7装备方案："),
        "setManage": ("Manage...", "管理…"),
        "specButton": ("Manage...", "管理…"),
        "specLabel": ("^7Passive tree:", "^7天赋树："),
        "slotHeader": ("^7Equipped items:", "^7已穿戴装备："),
        "weaponSwapLabel": ("^7Weapon Set:", "^7武器组："),
        "selectDBLabel": ("^7Import from:", "^7导入来源："),
        "uniqueButton": ("Uniques", "传奇装备"),
        "rareButton": ("Rare Templates", "稀有装备模板"),
        "priceDisplayItem": ("Trade for these items", "在市集搜索这些装备"),
        "editDisplayItem": ("Edit...", "编辑…"),
        "removeDisplayItem": ("Cancel", "取消"),
        "craftDisplayItem": ("Craft item...", "制作装备…"),
        "newDisplayItem": ("Create custom...", "创建自定义装备…"),
    },
    "SkillListControl": {
        "new": ("New", "新建"),
        "delete": ("Delete", "删除"),
        "deleteAll": ("Delete All", "删除全部"),
    },
    "SharedItemListControl": {
        "delete": ("Delete", "删除"),
    },
    "ItemListControl": {
        "sort": ("Sort", "排序"),
        "deleteUnused": ("Del Unused", "删除未用"),
    },
}
DISPLAY_TEXT = {
    "Modules/Build.lua": {
        '"Current build:  "..self.buildName': ("Current build:  ", "当前 BD："),
    },
    "Classes/CalcsTab.lua": {
        '"^7Main Skill: " .. self.build.skillsTab': ("^7Main Skill: ", "^7主技能："),
    },
    "Classes/ImportTab.lua": {
        'return "^7Character import status: "..': ("^7Character import status: ", "^7角色导入状态："),
        'return "^8Save location: " .. BuildExportPoE2': ("^8Save location: ", "^8保存位置："),
        'and "Retrieving paste.." or "Import"': ("Import", "导入"),
    },
    "Classes/SkillListControl.lua": {
        'self.label = "^7Socket Groups:"': ("^7Socket Groups:", "^7技能组："),
    },
    "Classes/SharedItemListControl.lua": {
        'self.label = "^7Shared items:"': ("^7Shared items:", "^7共享装备："),
    },
}
SLOT_LABELS = {
    "Weapon 1": "主手", "Weapon 2": "副手", "Helmet": "头盔", "Body Armour": "胸甲",
    "Gloves": "手套", "Boots": "鞋子", "Amulet": "项链", "Belt": "腰带",
    "Ring 1": "戒指 1", "Ring 2": "戒指 2", "Ring 3": "戒指 3",
    "Charm 1": "护符 1", "Charm 2": "护符 2", "Charm 3": "护符 3",
    "Flask 1": "药剂 1", "Flask 2": "药剂 2",
    "Arm 1": "手臂 1", "Arm 2": "手臂 2", "Leg 1": "腿部 1", "Leg 2": "腿部 2",
}
HELPER = '''local function uiLabel(english, simplifiedChinese)
    if os.getenv("POE2_ASSISTANT_LOCALE") == "zh-CN" then
        return simplifiedChinese
    end
    return english
end
'''


def translate(source, labels, display_text):
    if HELPER in source:
        source = source.replace(HELPER + "\n", "", 1)
        literal = r'"(?:[^"\\]|\\.)*"'
        source = re.sub(rf'uiLabel\(({literal}), {literal}\)', r'\1', source)
    for control, (english, chinese) in labels.items():
        label = json.dumps(english, ensure_ascii=False)
        pattern = rf'(self\.controls\.{control} = [^\n]*?, ){re.escape(label)}(?=,|\))'
        expression = f"uiLabel({label}, {json.dumps(chinese, ensure_ascii=False)})"
        source, count = re.subn(pattern, lambda match: match[1] + expression, source)
        if count != 1:
            raise ValueError(f"Expected one upstream label for {control}, found {count}")
    for anchor, (english, chinese) in display_text.items():
        label = json.dumps(english, ensure_ascii=False)
        expression = f"uiLabel({label}, {json.dumps(chinese, ensure_ascii=False)})"
        if source.count(anchor) != 1:
            raise ValueError(f"Expected one upstream display expression for {english}")
        source = source.replace(anchor, anchor.replace(label, expression, 1), 1)
    return HELPER + "\n" + source


def translate_slot_labels(source):
    rows = "\n".join(f'    ["{english}"] = "{chinese}",' for english, chinese in SLOT_LABELS.items())
    table = "local slotLabels = {\n" + rows + "\n}\n"
    anchor = "self.label = slotLabel or slotName"
    expression = anchor + "\n\tself.label = uiLabel(self.label, slotLabels[self.label] or self.label)"
    if source.startswith(HELPER):
        source = source.removeprefix(HELPER + "\n" + table + "\n").replace(expression, anchor, 1)
    if source.count(anchor) != 1:
        raise ValueError("Expected one item-slot display assignment")
    return HELPER + "\n" + table + "\n" + source.replace(anchor, expression, 1)


def write_launchers(engine):
    executable = "Path{space}of{space}Building-PoE2.exe"
    for locale in ("zh-CN", "en"):
        launcher = engine / f"Start-PoB-{locale}.cmd"
        launcher.write_text(
            f'@echo off\nsetlocal\nset "POE2_ASSISTANT_LOCALE={locale}"\n'
            f'start "" /d "%~dp0runtime" "%~dp0runtime\\{executable}"\n',
            encoding="ascii",
        )


def install_cjk(runtime, release, source):
    with release.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != CJK_RELEASE_SHA:
            raise ValueError("CJK release ZIP does not match the pinned SHA-256")
    xml = subprocess.check_output([
        "git", "-C", str(source), "show", f"{CJK_SOURCE_PIN}:runtime/lua/xml.lua"
    ])
    with ZipFile(release) as archive:
        libraries = [name for name in archive.namelist()
                     if "/" not in name and name.endswith(".dll") and name != "lua51.dll"]
        for name in (*libraries, *CJK_FONT_FILES):
            target = runtime / name
            content = archive.read(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != content:
                target.write_bytes(content)
    (runtime / "lua/xml.lua").write_bytes(xml)
    legacy_zlib = runtime / "z.dll"
    if legacy_zlib.exists():
        legacy_zlib.rename(runtime / "z.dll.original")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    parser.add_argument("--cjk-release", type=Path, required=True,
                        help="PathOfBuilding-PoE2-i18n v0.1.0 portable ZIP")
    parser.add_argument("--cjk-source", type=Path, required=True,
                        help="Git directory containing the pinned i18n commit")
    args = parser.parse_args()
    modules = {"Modules/Build.lua": LABELS}
    modules.update({f"Classes/{name}.lua": labels for name, labels in PAGE_LABELS.items()})
    updates = {}
    slots = "Classes/ItemSlotControl.lua"
    for name in modules.keys() | DISPLAY_TEXT.keys() | {slots}:
        module = args.engine / "src" / name
        original = module.read_bytes()
        source = original.decode("utf-8").replace("\r\n", "\n")
        localized = (translate_slot_labels(source) if name == slots
                     else translate(source, modules.get(name, {}), DISPLAY_TEXT.get(name, {})))
        if localized == source:
            continue
        if b"\r\n" in original:
            localized = localized.replace("\n", "\r\n")
        updates[module] = localized.encode("utf-8")
    install_cjk(args.engine / "runtime", args.cjk_release, args.cjk_source)
    for module, content in updates.items():
        module.write_bytes(content)
    write_launchers(args.engine)


if __name__ == "__main__":
    main()
