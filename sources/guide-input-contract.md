# A01 攻略 → BD 输入契约 v1（离线检查点）

输入是人工/后续提取器编写的 JSON，不是自然语言解析器，也不是可打开的 BD。
`scripts/guide_contract.py` 使用 Python 标准库校验并输出原输入副本、`missing_fields`、
`inferred_fields`；`pob_generation` 和 `mcp_acceptance` 始终为 `pending`。
`tests/fixtures/a01/` 中的攻略与合成查询夹具完全自编，不是网络攻略、游戏导出或真实赛季数据。
`AUTHORED-TEST` 只是隔离测试标签；不据此推荐技能或装备。

## 输入结构

顶层严格包含 `schema_version: 1`、`source`、`fields`。
`source` 包含非空 `id`（可复现的本地标识）、`kind`（`authored_prose` 或
`authored_structured`）、`title`、完整 `text`。原始结构化文本也保存在 text，不能只留摘要。
本版本只接受自编来源；真实 URL、抓取时间及内容授权留到真实来源接入时定义。

每个字段必须出现，值均为 `{value, origin, evidence, reason}`：

- `stated`：值已提供，evidence 是 source.text 的非空原文片段，reason 为 null。
- `inferred`：值为整理/推断结果，evidence 同上，reason 必须解释推断。不自动升格为原文事实。
- `missing`：value、evidence 均为 null，reason 说明缺失；不填引擎默认值。

校验验证形状、类型和引用存在性，不验证引文是否语义支持该值，候选查询仅核对固定索引，不能认定 ID 在目标游戏版本可用。
同一值可以有多个来源时，本小版本须先人工选择一份来源；冲突解决不在此检查点内。

| fields 键 | 非缺失时 value 类型 | 含义 / 后续映射 |
|---|---|---|
| realm | international / tencent | 助手上下文，不写入 PoB 字段 |
| league, game_version, stage | 非空字符串 | 赛季、游戏版本、单一阶段；不是从引擎 SHA 推导的值 |
| class_name, ascendancy_name | 非空字符串 | 原文名称，待 P03 映射；Build 保存 className/ascendClassName，新格式天赋使用 classInternalId/ascendancyInternalId |
| level | 1–100 整数 | Build/@level |
| main_skill_name, main_skill_id | 非空字符串 | 原文名称 / 后续解析的 granted effect skillId；不得用译名冒充 ID |
| main_skill_level, main_skill_quality | 正整数 / 非负整数 | Skills/Skill/Gem 的 level/quality；0 品质是已知值 |
| tree_version | 非空字符串 | Tree/Spec/@treeVersion，需要版本核对 |
| passive_nodes | 无重复的非负整数数组 | Spec/@nodes 的节点 ID；[] 表示明确空分配，null 才是未知 |
| equipment_text, config_text | 非空字符串 | 原文目标或带标记的整理备注，不是已解析物品或 Config 键值 |

除角色等级外，不臆造宝石等级/品质上限；由后续版本化数据校验。
此契约只描述一个阶段的一个主技能，不处理完整多阶段 BD、辅助组和武器切换。
新增支持必须升级契约，不能把未知键静默丢弃。

## 已核对的源码 schema 与缺口

来源是 `sources/pob.json` 固定 fork SHA `601768bd105869618c3d6581b883e5d7aeec91b2`，
本机 `/tmp/poe2-pob-source` 的同一 HEAD；未依赖在线文档或复制第三方实现。

- `src/Modules/Build.lua` 的 Load/Save（1138、1180 行）：角色 level 和保存的职业名；不是完整天赋初始化。
- `src/Classes/SkillsTab.lua:288` LoadSkill：Gem 的 skillId 或 game gemId/variantId 解析到引擎数据；有 level、quality、enabled，组有 mainActiveSkill 和武器组标记。
- `src/Classes/TreeTab.lua:493` 与 `PassiveSpec.lua:117`：Tree/Spec 的版本与 nodes；新格式 classInternalId、ascendancyInternalId，旧格式 classId、ascendClassId 有迁移。
- `src/Classes/ItemsTab.lua:1220`：Item 文本和 item id，由 Slot/ItemSet 的 slot name、itemId 关联。装备目标不能直接充当 Item。

两个样本均缺游戏版本、升华、主技能 ID、树版本和天赋节点、战斗配置；普通样本还缺服区、赛季、技能等级与品质。
结构化样本提供部分数值仍不是完整 BD。后续必须补 P03 名称/ID 映射及版本核对、辅助/其他技能组、
具体装备及槽位、天赋职业 ID 和配置语义；保留当前装备目标与推断备注。
生成器还需固定 fork 的完整加载/保存与打开验证。不得以 minimal XML 夹具或本校验通过代替它。
本地 MCP stdio 入口已接入本契约，范围、启动与验证见 [MCP 说明](guide-mcp.md)。
返回值的 `mcp_acceptance: pending` 指整项端到端验收，不能以输入校验代替攻略转 BD 验收。

## 复现

```sh
python3 -B scripts/guide_contract.py tests/fixtures/a01/prose.json
python3 -B scripts/guide_contract.py tests/fixtures/a01/structured.json
python3 -B -m unittest discover -s scripts -p 'test_guide_contract.py' -v
```

## 离线主技能候选返回

CLI 和 MCP 的校验结果附加 `main_skill_candidates`，不改变输入契约 v1。
`name`、`id` 分别用原始 `main_skill_name`、`main_skill_id` 做精确查询；
缺失字段对应 null，不自动补全，推断字段仍保留原 origin/reason。
查询复用 `SkillLookup`，固定索引须与 `sources/pob.json` 的来源三元组相符；
文件缺失、格式错误或版本不符时报错，不返回虚假的空候选成功结果。
候选含原查询、来源 SHA、声明位置及 single_candidate / ambiguous / not_found 状态；
不跨名称和 ID 回退，不翻译、裁剪或模糊匹配。

`name_id_consistency`：两侧均有候选且 ID 在名称候选集合中为 `overlap`，
两侧均有候选但集合不相交为 `conflict`；缺一侧或有未知值为 `not_comparable`。
`overlap` 不消除名称歧义，也不认定主技能资格或游戏版本兼容。
`confirmation` 始终为 `pending`，没有 selected 字段，不回填名称或 ID，不生成 BD。
`pob_generation`、`mcp_acceptance` 同样保留 pending。

`english-ambiguous.json` 与 `english-conflict.json` 是自编英文攻略，查询固定索引；
`skill-guides.synthetic.json` 配合虚构来源的 `skill-query-index.json` 验证歧义、
名称/ID 命名空间碰撞、交集、仅 ID、未知与缺失，不冒充真实引擎或赛季数据。

## 离线职业／升华候选返回

CLI 与唯一 MCP 工具新增 `class_ascendancy_candidates`，复用 `ClassLookup`，
不改变输入 v1；固定职业索引与 manifest 的仓库、分支、SHA 必须一致。
缺文件、错误索引或来源不符直接报错，即使攻略缺树版本也不伪装为空候选成功。

- `tree_version` 保留输入值；缺失时 `status=missing_tree_version`，未知时
  `status=unknown_tree_version`。两种情况下名称查询均为 null，不猜 default/latest，
  不根据游戏版本、职业或技能推导树版本。校验结果仍保留原攻略和 pending。
- 版本已知时 `status=ready` 仅表示可查询；`class_name`、`ascendancy_name`
  各自按英文名精确查询，缺失字段为 null，未知名返回 not_found。
  不裁剪、不翻译、不将文本名当编号，也不自动用职业候选过滤升华候选。
- 两侧都有候选时，按所属职业 integer ID 集合比较，交集非空为
  `class_ascendancy_consistency=overlap`，否则 conflict；缺一侧或未知名称为
  not_comparable。overlap 不消除同名歧义或表示已确认；conflict 保留双方完整候选。
- 返回固定来源、原查询、树版本及身份声明位置。推断值可以查询，但保持原有
  origin/reason 与 inferred_fields；不提升为已确认字段。返回副本不修改输入或索引。
  `confirmation`、`pob_generation`、`mcp_acceptance` 始终 pending，不选中或回填任何 ID。

`test_guide_class_candidates.py` 复用自编两版本索引并添加独立职业，构造完整自编攻略，
覆盖同名、归属交集／冲突、缺失与未知版本、版本隔离、未知名、推断及副本隔离。
`class-overlap.json`、`class-conflict.json`、`class-unknown-tree.json` 是自编英文攻略，
分别以固定索引验证 Warrior/Titan、Warrior/Deadeye 和未知版本，经 CLI 与真实 SDK stdio 返回。
这些样本不是客户端／真实攻略验收；不接入生成。

## 离线天赋节点候选返回

CLI 与唯一 MCP 工具附加 `passive_node_candidates`，复用 `NodeLookup`，输入 v1 不变。
固定节点索引必须匹配 manifest；缺文件、损坏或来源不符报错，即使输入缺少树版本或节点。
`tree_version` 保留输入值；缺失／未知版本分别返回 `missing_tree_version`／
`unknown_tree_version`，`nodes=null`，不查询或回退 default/latest，也不从其他字段推导版本。
已知版本但缺少 passive_nodes 时为 `missing_passive_nodes`、`nodes=null`；
明确空数组时为 `ready`、`nodes=[]`。ready 仅表示查询可执行，不表示节点均存在或分配有效。

已提供节点时，`nodes` 按输入顺序逐 ID 返回完整查询结果，存在为 single_candidate，
不存在为 not_found／空候选；只匹配该版 ID，不借用表键、string_id、名称或其他版本。
每项保留原查询、完整 source（含输入文件哈希）、版本元数据与声明、完整节点与声明。
外层 source 同样保留；返回副本不修改攻略或索引。未知节点不丢弃、不回填或自动选择。
原字段的 origin/evidence/reason、missing_fields 和 inferred_fields 不变；
`confirmation`、`pob_generation`、`mcp_acceptance` 始终 pending，不检查连通性、点数或生成 BD。

`test_guide_node_candidates.py` 复用自编两版本节点索引，构造完整攻略验证版本隔离、
缺失／未知版本、缺失节点字段与 ID、空数组、来源、推断及副本隔离；
另以固定索引 0_1／0_5 自编攻略验证 CLI。SDK stdio 用同类攻略核对完整文本及结构化返回。

## 离线候选确认契约 v1

候选结果现在附带 `confirmation_context`。它包含各索引完整 `sources`
（skills/classes/nodes，含 repository、branch、commit SHA，节点还含文件哈希）、
原 `tree_version`、`snapshot_sha256`。快照哈希覆盖添加 context 前的完整校验结果：
原攻略、来源原文、证据/推断、全部候选及声明、缺失字段和 pending 状态。
算法为 UTF-8 JSON、sort_keys=True、ensure_ascii=False、separators=(',', ':')、
allow_nan=False 后取 SHA-256；对象键顺序不影响哈希，数组顺序及 JSON 类型影响哈希。

调用 `guide_confirmation.validate_confirmation(guide, confirmation)`，传入原攻略和明确选择。
CLI 使用 `python3 -B scripts/guide_contract.py guide.json --confirmation confirmation.json`；
省略该参数时只查询候选。确认文件须为完整 confirmation 对象，null 或损坏/缺失文件报错。
唯一 MCP 工具接受 `{"guide": <原攻略>, "confirmation": <完整确认对象>}`；
省略 confirmation 或显式 null 时只查询，guide 仍是唯一必填参数。
confirmation 顶层严格为以下三键，各 selection 键也必须出现。以自编
`class-overlap.json` 为 guide、用户明确选中 Warrior/Titan 为例：

```python
from guide_contract import validate_guide
from guide_confirmation import validate_confirmation

result = validate_guide(guide)
confirmation = {
    "schema_version": 1,
    "context": result["confirmation_context"],
    "selection": {
        "main_skill_id": None,
        "class_integer_id": 6,
        "ascendancy": {"class_integer_id": 6, "id": "Titan"},
        "passive_node_ids": None,
    },
}
validated = validate_confirmation(guide, confirmation)
```

- context 必须是原查询返回的完整对象；校验器用当前固定本地索引重新查询，逐上下文
  严格比较（含类型）。攻略、查询候选/声明、来源 SHA/文件哈希或树版本变更均拒绝旧输入，
  须重新展示候选和收集选择。不信任调用方提交的候选记录。各索引须同仓库、分支、SHA。
- 必须有在职业和节点索引中均已知的显式树版本；missing/unknown/default/latest 不获回退。
- main_skill_id 只能来自原 name/id 查询候选的并集，允许用户明确解决两侧冲突；
  不用其值重查全索引后扩大原候选集合，不验证技能适用性或游戏版本兼容性。
- class_integer_id 是原职业名称候选的非负整数 integer_id，不是 source_index。
  升华选择为 `{"class_integer_id": 7, "id": "Alpha"}`（自编示例），
  必须同时明确选择相同所属职业；二元组须在原升华名称候选中，不能用 internal_id 或序号替代。
- passive_node_ids 是原逐节点查询候选 ID 的无重复非负整数子集，保留用户选择顺序；
  拒绝原文有 ID 但查询 not_found 的节点，也拒绝索引中存在但未返回的节点。
- 允许部分选择；null 表示未选，[] 明确选择空节点数组。缺失 passive_nodes 时不能提交 []。
  全 null 不构成选择；不自动补 ID、合并名称、自动选择唯一候选或确认推断字段。

成功额外返回 `candidate_selection: {status: "validated", input: <确认输入副本>}`，
原查询结果和攻略完全保留，各候选 confirmation、pob_generation、mcp_acceptance 仍 pending。
validated 只代表选择属于当前候选，不代表完整 BD、所有字段已确认、节点连通或点数合法。
上下文是无状态内容绑定，不是用户身份认证、签名或防重放凭证；相同快照可重复校验。
失败抛 ValueError，不输出部分选择或 BD，不写文件、不执行 Lua。

自编两版本、同名歧义及冲突夹具见 `scripts/test_guide_confirmation.py`，运行：
`python3 -B -m unittest discover -s scripts -p 'test_guide_confirmation.py' -v`。

确认入口错误恢复：CLI 失败返回退出码 1，stderr 说明错误，stdout 为空；
MCP 失败返回 isError 工具结果，会话可继续。过期后重新查询并明确选择，
使用新的 confirmation_context 重试；不得只替换旧输入的 context 自动重放选择。
入口不写攻略、确认文件或 BD；成功仅增加 candidate_selection。
入口自编回归见 `scripts/test_guide_confirmation_cli.py` 和 `tests/test_guide_mcp.py`，
覆盖过期来源与攻略、越界节点、错误输入、重新查询恢复和完整原结果保留。

单主技能组生成前必填项、新格式 ID 映射和加载语义见 [生成前契约](guide-generation-contract.md)。
该独立 Python 校验器尚未接入 CLI/MCP，输入齐全也不代表可生成 BD。
