# A01 单主技能组生成前输入契约 v1

本检查点只读取本地固定源码和索引，以自编攻略测试；不生成 XML、PoB 代码或 .build，
不执行 Lua。调用 `scripts/guide_generation_contract.py` 中的
`validate_generation_inputs(guide, confirmation, group)`。这是独立 Python 契约，
尚未接入 CLI/MCP；现有输入和候选确认入口不变。

## 已核对的加载语义

依据 `sources/pob.json` 固定的 PoB 提交
`601768bd105869618c3d6581b883e5d7aeec91b2`。

- `SkillsTab.lua:288–400`：组 enabled 仅显式 active/enabled=true 时启用；
  mainActiveSkill/Calcs 缺失默认 1。Gem enabled 缺失默认 true，level/quality 转数值。
  gemId 是游戏 ID，通过 gemsByGameId + variantId 解析；未知 variant 会选第一个 variant。
  gemId 存在时优先于 skillId，即使 gemId 未解析也不走 skillId 分支。
  skillId 是 data.skills 的 granted-effect ID；nameSpec 不能代替稳定身份。
- `SkillsTab.lua:403–553`：旧格式直接 Skill 被装入 set 1；新格式使用
  Skills/@activeSkillSet、SkillSet/@id。Save 同时保存 skillId 和可用的游戏 gemId/variantId。
- `SkillsTab.lua:1296–1391`：ProcessSocketGroup 仍可能按名称迁移，校验/调整等级，
  hideFromSideBar 技能不能作为 active；双武器组均 false 会重置为 true/true。
  source/slot、装备与 reservesInAllWeaponSets 还可能改变可用武器组。
- `SkillsTab.lua:1428`：mainActiveSkill 指该组生成的 active-skill 列表序号，
  不等同于 Gem 序号。单 Gem 也不能证明只有一个 effect。
- `Build.lua:1138–1190`：level 默认 1 并限于 1–100；mainSkillIndex 优先于
  mainSocketGroup，均缺时默认 1；targetVersion 缺时用 legacyTargetVersion。
  Save 写 className/ascendClassName；Load 不以这两个名字初始化职业天赋。
- `PassiveSpec.lua:175–213,283–298`：新格式 classInternalId 是职业 integer_id；
  ascendancyInternalId 是升华 internal_id。旧 classId/ascendClassId 是另一套索引且有迁移。
  空 ascendancyInternalId 表示未升华，不能把未知升华当成空串。

## 输入、映射与缺失

必须重新执行 `validate_confirmation`，绑定原攻略、树版本及完整索引来源；
不接受调用方提交的 validated 结果。部分选择仍可检查，但返回 missing_inputs。
候选冲突可由显式选择解决，推断、原文中未知节点、未选候选全部保留。

必填事实：realm、league、game_version、stage、level、tree_version、
main_skill_level、main_skill_quality。前四项是助手上下文；不把 game_version 当 targetVersion。
必填选择：main_skill_id、class_integer_id、ascendancy、passive_node_ids。
技能/职业/升华名称与原始技能 ID 可缺，由明确选中的候选给出身份；不回填原攻略。
null 节点是未选，[] 是明确无节点。v1 尚不能明确选择“未升华”；null 仍算缺失，
不能用于未升华开荒草稿。equipment_text/config_text 只是备注，不算装备/配置解析完成。

`group` 严格包含下面六键；每键允许 null，表示待补：

```python
group = dict(enabled=True, set1=True, set2=False, gem_enabled=True,
             main_active_skill=1, main_active_skill_calcs=1)
```

范围限定为一个普通 SkillSet、一个组、一个 Gem，不含 source/slot、辅助或其他组。
enabled/gem_enabled 必须 true；set1/set2 为严格布尔且不能同时 false。
两个 active 序号只接受整数 1；其对应 effect 资格仍 pending。多组/其他属性报错。
固定组结构序号 1 是本契约的结构决定；不从未知攻略事实推导数值。
技能等级为正整数，品质为非负整数，角色等级 1–100；逐技能等级/品质合法范围仍待查。

成功返回原候选确认结果，附 `generation_input_check`：
schema_version=1、status=missing_inputs/inputs_complete、missing_inputs、group 副本、
mapping 和 pending_checks。mapping 为带目的字段路径的类型化值，不是可写入文件的 XML。
缺失值保持 null；Build.level/Gem.level/quality 来自原事实；Gem.skillId 来自明确选择，
不写 gemId/variantId，避免错误优先级或 variant 回退。
职业 integer_id → Spec.classInternalId；升华 id 按所属职业对应到 internal_id →
Spec.ascendancyInternalId；英文名仅映射 Build 显示字段；节点保持选中顺序。
不用 source_index、ascendancy_index 或名称冒充稳定 ID。

inputs_complete 只表示本契约必填齐全，不能作为允许生成的判据。
pending_checks 始终包含 targetVersion 映射、宝石身份与主技能资格、等级品质与 effect 选择、
天赋分配合法性、装备/配置语义、固定引擎加载保存。技能索引包含辅助、怪物及物品技能；
名字/ID 存在不证明它可作为玩家主技能，也不证明与声明游戏版本兼容。
pob_generation/mcp_acceptance 和候选 confirmation 保持 pending，不启动 PoB。
错误抛 ValueError；输入、索引和文件不修改。

## 自编回归

`python3 -B -m unittest discover -s scripts -p 'test_guide_generation_contract.py' -v`

合成夹具刻意让 integer_id != source_index、升华 id != internal_id；
固定索引样本只核对自编 Warrior/Titan/FireballPlayer 映射，不作为构筑建议。
覆盖缺失/部分选择、0 品质/空节点、原结果与推断保留、副本隔离、严格类型、
禁用/武器组改写、过期与越界选择；没有引擎/客户端/Windows 验收。
