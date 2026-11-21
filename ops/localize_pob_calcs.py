"""Translate PoB calculation labels at display boundaries."""

import argparse
import json
from pathlib import Path


LABELS = {
    "View Skill Details": "技能详情", "Calculation Mode": "计算模式",
    "Skill Hit Damage": "技能击中伤害", "Skill Average Hit": "技能平均击中",
    "Average Hit": "平均击中伤害", "Average Damage": "平均伤害",
    "Attack Rate": "每秒攻击次数", "Cast Rate": "每秒施法次数",
    "Cast Time": "施法时间", "Hit Rate": "每秒击中次数",
    "Crit Chance": "暴击率", "Crit Multiplier": "暴击伤害倍率",
    "Hit Chance": "命中率", "Hit DPS": "击中每秒伤害",
    "DoT DPS": "持续每秒伤害", "Bleed DPS": "流血每秒伤害",
    "Ignite DPS": "点燃每秒伤害", "Poison DPS": "中毒每秒伤害",
    "Total DPS inc. Ignite": "总 DPS（含点燃）",
    "Total DPS inc. Bleed": "总 DPS（含流血）",
    "Total DPS inc. Poison": "总 DPS（含中毒）",
    "Total DPS inc. DoT": "总 DPS（含持续伤害）",
    "Effective Hit Pool": "有效生命池", "Total Life": "总生命",
    "Energy Shield": "能量护盾", "Total Mana": "总魔力", "Total Spirit": "总精魂",
    "Armour": "护甲", "Evasion rating": "闪避值",
    "Fire Resistance": "火焰抗性", "Cold Resistance": "冰霜抗性",
    "Lightning Resistance": "闪电抗性", "Chaos Resistance": "混沌抗性",
    "Mana Cost": "魔力消耗", "Mana Cost per Second": "每秒魔力消耗",
    "Mana Cost per second": "每秒魔力消耗",
    "Mana Regen": "魔力回复", "Strength": "力量", "Dexterity": "敏捷",
    "Intelligence": "智慧", "Phys Max Hit": "物理最大承伤",
    "Elemental Max Hit": "元素最大承伤", "Chaos Max Hit": "混沌最大承伤",
    "Socket Group": "技能组", "Search": "搜索",
    "Both": "两组", "Set 1": "第 1 组", "Set 2": "第 2 组",
    "Active Skill": "主动技能", "Stat Set": "参数组",
    "Skill Part": "技能部分", "Skill Stages": "技能阶段", "Active Mines": "生效地雷",
    "Show Minion Stats": "显示召唤物属性", "Minion": "召唤物",
    "Spectre Library": "灵体库", "Beast Library": "野兽库",
    "Minion Skill": "召唤物技能", "Minion Skill Stat Set": "召唤物技能参数组",
    "Unbuffed": "无增益", "Buffed": "有增益", "In Combat": "战斗中",
    "Effective DPS": "有效 DPS", "Aura and Buff Skills": "光环与增益技能",
    "Combat Buffs": "战斗增益", "Curses and Debuffs": "诅咒与减益",
    "All Types": "全部类型", "Physical": "物理", "Lightning": "闪电",
    "Cold": "冰霜", "Fire": "火焰", "Chaos": "混沌",
    "Added Min": "最小附加伤害", "Added Max": "最大附加伤害",
    "Total Increased": "总计提高", "Total More": "总计额外提高",
    "Effective DPS Mod": "有效 DPS 倍率", "MH Total Increased": "主手总计提高",
    "MH Total More": "主手总计额外提高", "MH Eff. DPS Mod": "主手有效 DPS 倍率",
    "OH Total Increased": "副手总计提高", "OH Total More": "副手总计额外提高",
    "OH Eff. DPS Mod": "副手有效 DPS 倍率", "Player modifiers": "角色修正",
    "Enemy modifiers": "敌人修正", "Conversions": "伤害转化",
    "Accuracy": "命中值", "Chance to Hit": "命中率", "Attack/Cast Rate": "攻击／施法速率",
    "Attack time": "攻击时间", "Cast time": "施法时间",
    "Attacks per second": "每秒攻击次数", "Casts per second": "每秒施法次数",
    "Inc. Attack Speed": "攻击速度提高", "More Attack Speed": "额外攻击速度",
    "Inc. Cast Speed": "施法速度提高", "More Cast Speed": "额外施法速度",
    "Inc. Crit Chance": "暴击率提高", "Crit Effect Mod": "暴击效果倍率",
    "Skill DPS": "技能 DPS", "Skill type": "技能类型", "Ignite": "点燃",
    "Poison": "中毒", "Bleed": "流血", "Non-Damaging Ailments": "非伤害类异常状态",
    "Crits": "暴击", "Damage over Time": "持续伤害", "Damage Taken": "承受伤害",
    "Enemy Damage": "敌人伤害", "Attributes": "属性", "Armour Defense": "护甲防御",
    "Life": "生命", "Mana": "魔力", "Spirit": "精魂", "Evasion": "闪避",
    "Evade Chance": "闪避率", "Block": "格挡", "Block Chance": "格挡率",
    "Dodge": "躲避", "Dodge Chance": "躲避率", "Damage Avoidance": "伤害避免",
    "Deflection": "偏斜", "Deflection Rating": "偏斜值", "Deflect Chance": "偏斜率",
    "Deflect Effect": "偏斜效果", "Effective DoT Pool": "持续伤害有效承伤池",
    "Fire Resist": "火焰抗性", "Cold Resist": "冰霜抗性",
    "Lightning Resist": "闪电抗性", "Chaos Resist": "混沌抗性",
    "Ailment Threshold": "异常状态阈值", "Damage Mod.": "伤害修正",
    "Value": "数值", "Stat": "属性", "Skill types": "技能类型", "Notes": "备注",
    "Source": "来源", "Source Name": "来源名称", "Skill": "技能",
    "Base": "基础值", "More/less": "额外提高／降低", "Inc/red": "提高／降低",
    "Efficiency": "效率", "Efficiency More/less": "额外提高／降低效率",
    "Count": "数量", "Reservation": "保留", "From": "来源",
    "Converted Damage": "转化伤害", "Total": "合计", "Conversion": "转化",
    "Name": "名称",
    "Enemy Ail. Thresh.": "敌人异常阈值", "Max Ignite Stacks": "最大点燃层数",
    "Stack Potential": "叠加潜力", "Average Ignite Roll": "平均点燃掷值",
    "Chance to Ignite": "点燃几率", "Magnitude Effect": "效果幅度倍率",
    "Source Fire": "来源火焰伤害", "Ignite Duration": "点燃持续时间",
    "Dmg. of all Ignites": "全部点燃伤害", "Stun Buildup": "晕眩积累",
    "Unmitigated %": "未减免比例", "Mitigated hits": "减免后等效击中数",
    "Enemy miss chance": "敌人未命中率", "Hits before death": "致死击中数",
    "Time before death": "致死时间", "Maximum Hit Taken": "最大承伤",
    "Recoup and Hit Taken Over Time": "补偿与延后承受的击中伤害",
    "Dots and Build Degens": "持续伤害与资源流失", "Enemy Degens": "敌人持续伤害",
    "DoT taken": "承受持续伤害", "Total Pool": "总承伤池",
    "Base from Armours": "防具提供的基础值", "Global Base": "全域基础值",
    "Inc. from Tree": "天赋树提供的提高", "Resists": "抗性",
    'Effective "Health" Pool': "有效承伤池", "Damaging Hits": "造成伤害的击中",
    "Runic Ward": "符文结界", "Phys. Dmg. Reduct": "物理伤害减免",
    "Fire Dmg. Reduct": "火焰伤害减免", "Cold Dmg. Reduct": "冰霜伤害减免",
    "Light. Dmg. Reduct": "闪电伤害减免", "Chaos Dmg. Reduct": "混沌伤害减免",
    "Melee Evade Ch.": "近战闪避率", "Proj. Evade Ch.": "投射物闪避率",
    "Sources": "来源", "Recovery": "回复", "Recovery modifiers": "回复修正",
    "FasterRecoup": "补偿加速", "Faster Recoup": "补偿加速",
    "Net Life Recovery": "净生命回复", "Net Mana Recovery": "净魔力回复",
    "Net ES Recovery": "净能量护盾回复",
    "Base from Gear": "装备提供的基础值", "Total Base": "总基础值",
    "Reserved": "已保留", "Unreserved": "未保留", "Recharge Rate": "充能速率",
    "Recharge Delay": "充能延迟", "Gem Req Mod": "宝石需求倍率",
    "Item Req Mod": "装备需求倍率", "Weapon Req Mod": "武器需求倍率",
    "Str. Required": "力量需求", "Dex. Required": "敏捷需求",
    "Int. Required": "智慧需求", "Dexterity Required": "敏捷需求",
    "Intelligence Required": "智慧需求", "Strength Required": "力量需求",
    "Phys. Damage Reduction": "物理伤害减免", "%Inc Life": "生命提高",
    "Skill type-specific Stats": "技能类型专属属性", "Gem Level": "宝石等级",
    "Mana per second": "每秒魔力消耗", "Projectile Count": "投射物数量",
    "Proj. Speed Mod": "投射物速度倍率", "Curse Limit": "诅咒上限",
    "Other Effects": "其他效果", "Stun Threshold": "晕眩阈值",
    "Stun Duration": "晕眩持续时间", "Stun Chance": "晕眩几率",
    "Block Stun Duration": "格挡晕眩时间", "Presence Radius": "存在范围",
    "Surrounded Radius": "被包围范围", "Chance to Blind": "致盲几率",
    "Chance to Daze": "眩晕几率", "Inc. Quiver Effect": "箭袋效果提高",
    "Inc. Item Quantity": "物品数量提高", "Inc. Item Rarity": "物品稀有度提高",
    "MS While Casting": "施法时移动速度", "Movement Speed": "移动速度",
    "Movement Speed Modifier": "移动速度调整", "Skill Movement Speed": "技能移动速度",
    "Taken As": "伤害承受类型", "Hit taken Mult.": "击中承伤倍率",
    "Hit taken": "击中承伤", "Taken From Block": "格挡后承伤",
    "Spell Ddg. Chance": "法术躲避率", "Eva. as Deflection": "闪避转偏斜",
    "Arm. as Deflection": "护甲转偏斜", "Other Defences": "其他防御",
    "Other Avoidance": "其他伤害避免", "Other Ailment Defences": "其他异常状态防御",
    "Light Radius Mod": "照亮范围倍率", "Curse Effect on You": "自身受到的诅咒效果",
    "Exposure Effect": "曝露效果", "Wither Effect": "凋零效果",
    "Weap. Swap Speed": "武器切换速度", "Rage": "怒火", "Charges": "能量球",
    "Flasks": "药剂", "Utility Flasks": "功能药剂", "Life Flasks": "生命药剂",
    "Mana Flasks": "魔力药剂", "Charms": "护符", "Inc. Effect": "效果提高",
    "Inc. Duration": "持续时间延长", "Inc. Charges Gain": "充能获取提高",
    "Inc. Charges Used": "充能消耗提高", "% to not Consume": "不消耗充能几率",
    "Charge on crit %": "暴击获充能几率", "Charges/s": "每秒充能",
    "Att. per second": "每秒攻击次数", "Inc. Att. Speed": "攻击速度提高",
    "More Att. Speed": "额外攻击速度", "Hit Damage": "击中伤害",
    "DMG Mod.": "伤害修正", "Eff. DPS Mod": "有效 DPS 倍率",
    "Crit Bifurcates": "暴击分叉", "Impale Chance": "穿刺几率",
    "K.B. Chance": "击退几率", "K.B. Dist.": "击退距离",
    "PvP Average Hit": "PvP 平均击中", "Stored Damage": "储存伤害",
    "Source Physical": "来源物理伤害", "Source Lightning": "来源闪电伤害",
    "Source Cold": "来源冰霜伤害", "Source Chaos": "来源混沌伤害",
    "Weapon Range": "武器范围", "Active Minion Limit": "召唤物数量上限",
    "Minion Revival Time": "召唤物复活时间", "Companion Ally": "同伴",
    "Max Chain Count": "最大连锁次数", "Terrain Chain": "地形连锁",
    "Player": "角色", "Spirit Reserve Mod": "精魂保留倍率",
    "Duration Mod": "持续时间倍率", "Area of Effect Mod": "效果范围倍率",
    "AoE Radius": "效果范围半径", "Radius": "半径", "Effective Crit Chance": "有效暴击率",
    "Shock Effect Mod": "感电效果倍率", "Chance to Shock": "感电几率",
    "Shock Duration": "感电持续时间", "Maximum Shock": "最大感电效果",
    "Show stats for the minion instead of the player.": "切换为显示召唤物的统计数据。",
    "Manage Spectres...": "管理灵体…", "Manage Beasts...": "管理野兽…",
    "Blind Avoid Ch.": "避免致盲几率", "Shock Avoid Ch.": "避免感电几率",
    "Freeze Avoid Ch.": "避免冻结几率", "Chill Avoid Ch.": "避免冰缓几率",
    "Ignite Avoid Ch.": "避免点燃几率", "Sap Avoid Ch.": "避免精疲力尽几率",
    "Brittle Avoid Ch.": "避免易碎几率", "Scorch Avoid Ch.": "避免焦灼几率",
    "Bleed Avoid Ch.": "避免流血几率", "Poison Avoid Ch.": "避免中毒几率",
    "Impale Avoid Ch.": "避免穿刺几率", "Curse Avoid Ch.": "避免诅咒几率",
    "Silence Avoid Ch.": "避免沉默几率", "Crit Reduction": "暴击伤害减免",
    "Corr Blood Immune": "免疫腐化之血", "Maim Immune": "免疫瘫痪",
    "Hinder Immune": "免疫阻碍", "Knockback Immune": "免疫击退",
    "Blind Duration": "致盲持续时间", "Freeze Duration": "冻结持续时间",
    "Chill Duration": "冰缓持续时间", "Sap Duration": "精疲力尽时间",
    "Brittle Duration": "易碎持续时间", "Scorch Duration": "焦灼持续时间",
    "Bleed Duration": "流血持续时间", "Poison Duration": "中毒持续时间",
    "Freeze Effect": "冻结效果", "Chill Effect": "冰缓效果", "Shock Effect": "感电效果",
    "Ignite Effect": "点燃效果", "Sap Effect": "精疲力尽效果", "Brittle Effect": "易碎效果",
    "Scorch Effect": "焦灼效果", "Bleed Effect": "流血效果", "Poison Effect": "中毒效果",
}
MODE_HINT = """此设置控制计算页的统计方式。侧栏始终显示有效 DPS 模式下的数值。

无增益：不计入光环、增益和其他辅助效果，相当于站在城镇中。
有增益：计入光环和增益技能，相当于在藏身处开启这些技能。
战斗中：进一步计入能量球、猛攻等战斗增益，显示战斗中的面板数据。
有效 DPS：进一步计入诅咒以及敌人的抗性和状态，估算实际 DPS。"""

REPLACEMENTS = {
    "Modules/Build.lua": (
        ("labelColor..statData.label..", "labelColor..calcLabel(statData.label)..", 2),
        ('color, valStr, statData.label)', 'color, valStr, calcLabel(statData.label))', 1),
        ('valStr = color .. formatNumSep(valStr)', 'valStr = color .. calcLabel(formatNumSep(valStr), "statUnit")', 1),
        ('{ height = 18, "^7Minion:" }', '{ height = 18, "^7"..calcLabel("Minion:") }', 1),
        ('{ height = 18, "^7Player:" }', '{ height = 18, "^7"..calcLabel("Player:") }', 1),
    ),
    "Classes/CalcSectionControl.lua": (
        ('(subSec.label or "")', '(calcLabel(subSec.label) or "")', 2),
        ('"VAR BOLD", subSec.label)', '"VAR BOLD", calcLabel(subSec.label))', 1),
        ('..rowData.label.."^7:"', '..calcLabel(rowData.label).."^7:"', 2),
        ('formatCalcStr(colData.format, actor, colData)',
         'formatCalcStr(calcLabel(colData.format, true), actor, colData)', 1),
        ('formatCalcStr(subSec.data.extra, actor)',
         'formatCalcStr(calcLabel(subSec.data.extra, true), actor)', 1),
    ),
    "Classes/CalcsTab.lua": tuple(
        (f'label = "{label}", buffMode', f'label = calcLabel("{label}"), buffMode', 1)
        for label in ("Unbuffed", "Buffed", "In Combat", "Effective DPS")
    ) + (('end, [[\nThis controls the calculation',
          'end, calcLabel([[\nThis controls the calculation', 1),
         ('This estimates your true DPS.]])', 'This estimates your true DPS.]], "modeHint"))', 1),
         ('"", "Search", "%c"', '"", calcLabel("Search"), "%c"', 1),
         ('end, "Show stats for the minion instead of the player.")',
          'end, calcLabel("Show stats for the minion instead of the player."))', 1),
         ('}, "Manage Spectres...", function()', '}, calcLabel("Manage Spectres..."), function()', 1),
         ('}, "Manage Beasts...", function()', '}, calcLabel("Manage Beasts..."), function()', 1)),
    "Classes/CalcBreakdownControl.lua": (
        ('"VAR", col.label)', '"VAR", calcLabel(col.label))', 3),
        ('"VAR", section.label..":")', '"VAR", calcLabel(section.label)..":")', 1),
        ('"^7"..section.label..":"', '"^7"..calcLabel(section.label)..":"', 1),
    ),
}
IMPORT = 'local calcLabel = LoadModule("Modules/AssistantCalcLabels")\n'


def patch_display(source, replacements):
    for original, replacement, expected in replacements:
        if source.count(replacement) == expected and original not in source:
            continue
        if source.count(original) != expected or replacement in source:
            raise ValueError(f"Unexpected PoB display expression: {original}")
        source = source.replace(original, replacement)
    return source if source.startswith(IMPORT) else IMPORT + source


def install(engine):
    source = engine / "src"
    changes = {}
    for name, replacements in REPLACEMENTS.items():
        path = source / name
        raw = path.read_bytes()
        newline = "\r\n" if b"\r\n" in raw else "\n"
        text = raw.decode("utf-8").replace("\r\n", "\n")
        changes[path] = patch_display(text, replacements).replace("\n", newline).encode("utf-8")
    entries = "\n".join(
        f"    [{json.dumps(original)}] = {json.dumps(chinese, ensure_ascii=False)},"
        for original, chinese in LABELS.items()
    )
    module = (
        f"local labels = {{\n{entries}\n}}\n"
        f"local modeHint = [[{MODE_HINT}]]\n"
        'local chinese = os.getenv("POE2_ASSISTANT_LOCALE") == "zh-CN"\n'
        """return function(label, context)
    if not chinese or not label then
        return label
    end
    if context == "modeHint" then
        return modeHint
    end
    if context == "statUnit" then
        local units = { m = " 米", s = " 秒" }
        local value, unit = label:match("^(.*%d)([ms])$")
        return value and value .. units[unit] or label
    end
    local color, uncolored = label:match("^(%^x%x%x%x%x%x%x)(.*)$")
    local plain = uncolored or label
    if labels[plain] then
        return (color or "") .. labels[plain]
    end
    local hand, stat = plain:match("^([MO]H) (.+)$")
    if hand and labels[stat] then
        return (color or "") .. (hand == "MH" and "主手" or "副手") .. labels[stat]
    end
    local name, suffix = plain:match("^([^:]+):(.*)$")
    if name and labels[name] then
        local value = suffix:match("^ (.+)$")
        return (color or "") .. labels[name] .. "：" .. (labels[value] or suffix)
    end
    if context then
        local translated = label:gsub("} to {", "} 至 {")
        translated = translated:gsub("} ?ms$", "} 毫秒")
        translated = translated:gsub("} ?/s$", "} /秒")
        translated = translated:gsub("}s$", "} 秒")
        translated = translated:gsub("}m$", "} 米")
        return translated
    end
    return label
end
"""
    )
    for path, content in changes.items():
        path.write_bytes(content)
    (source / "Modules/AssistantCalcLabels.lua").write_bytes(module.encode("utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    install(parser.parse_args().engine)
