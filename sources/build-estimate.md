# M04 离线逐槽报价汇总

离线汇总聚合调用方提供的逐槽参考报价；新增的 BD 入口读取本地 XML 装备清单，不匹配词缀、不查询市场或汇率。夹具为自编算术样本，不是真实市场观察或词缀匹配证据。P02/M03 联调及 M04 整项验收仍待完成。

```sh
python3 -B scripts/assistant.py estimate-build tests/fixtures/m04/quotes.synthetic.json
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

函数 `aggregate_quotes(slots, *, realm, league)` 和 CLI 接受明确的服区、赛季。CLI 输入为 `{context: {realm, league}, slots: [...]}`。`realm` 为 `international` 或 `tencent`；每条归一化挂单的服区和赛季必须与上下文一致。

统一助手入口的 `estimate-build <input.json>` 子命令输出 JSON 到 stdout，成功退出 0；读文件、解析或契约错误退出 1，错误写入 stderr，无部分估价输出。无需 PoB 安装、第三方 Python 包或网络。原 `scripts/build_estimate.py <input.json>` 仍可用；两者调用同一个 `estimate_file` / `aggregate_quotes` 实现。`launch-pob` 子命令继续用于独立启动 PoB。

上述自编 5 槽夹具应得到 `quoted_slot_count: 3`、`subtotals_by_currency: {divine: 2, exalted: 0.3}`，以及 Boots 的 `missing_price` 和 Gloves 的 `missing_listing`；4 个槽位有参考挂单。结果包含所有输入槽位，不丢弃缺价槽位。

每行字段：

- `slot`：非空且唯一的调用方槽位标识，例如 `Ring 1` 和 `Ring 2`。不猜测武器组、空槽或完整槽位清单。
- `matched_affixes`：调用方提供的匹配词缀文本数组，允许空数组；本模块保留原文，不验证匹配正确性。
- `listing`：M01/M02 格式的已选参考挂单，保留 `id/realm/league/item/price` 及附加字段。无匹配时显式传 null，此时匹配词缀必须为空。挂单存在而未标价时 `price` 显式为 null。

调用方负责提供拟估价 BD 的完整目标槽位清单，并为每槽选择一个参考挂单；本模块不选择最低价或计算挂单均价。一个挂单即一份槽位参考报价，同一参考挂单可以用于两个不同槽位，各计一次。挂单只是参考，并不保证可购买相应数量。

输出 `slots` 按输入顺序保留槽位、匹配词缀和完整参考挂单，增加 `status`：`quoted`、`missing_price` 或 `missing_listing`。`matched_slots` 包含有参考挂单的槽位（含未标价挂单）；`missing_slots` 列出全部缺报价槽位及原因，两者可能重叠。`quoted_slot_count` 只计有价槽位。

`subtotals_by_currency` 只累加有价槽位，按原始通货标识分别返回，不将缺价视为零。不提供跨通货总价，也不接受或推断换汇表；后续汇率接入可复用 M06 的同服同赛季方向约定。即使所有输入槽位都有价，也只代表这些参考报价的小计，不证明整套 BD 的完整价格。全部缺价时小计为空对象。

金额必须为正有限数；无效金额、重复槽位、跨服/跨赛季挂单及不完整输入报错。使用十进制累加后输出 JSON 数值，例如 0.1 + 0.2 输出 0.3；输出受有限浮点表示范围限制。输入不修改，返回对象与输入隔离；CLI 全部计算成功后才输出，失败非零退出且无部分结果。

后续市场接入沿用同一边界：P02 提供实际 BD 的完整目标槽位，M03 按明确服区和赛季查询/筛选，M01/M02 归一化挂单。组装层把每槽选定挂单及已核对的匹配词缀填入当前 JSON 契约，再交给本汇总函数或助手入口。无匹配仍保留该槽并传 `listing: null`，有挂单但无报价保留挂单并传 `price: null`；查询失败应由查询层报告，不能伪装成无匹配。参考挂单选择、词缀匹配及数据时效由该层负责，汇总层继续只校验上下文并计算。

本轮增加自编原始挂单到槽位的离线组装验证；实际 BD 完整性、双服真实数据、UI 或 Windows 对照仍未验证。跨通货估价另需接入有来源/时间的同服同赛季汇率，不改变当前原通货小计含义。

## 离线原始挂单组装

```sh
python3 -B scripts/assistant.py estimate-build --from-listings tests/fixtures/m04/international.selections.synthetic.json
python3 -B scripts/assistant.py estimate-build --from-listings tests/fixtures/m04/tencent.selections.synthetic.json
```

清单字段为 `context`、`response_file` 和完整目标 `selections`。`response_file` 是本地原始 JSON 路径，相对清单所在目录解析，不受启动目录影响；不下载数据。两个清单分别引用 M01/M02 原有自编挂单，预期均为 2 个有价槽位，Ring 2 和 Gloves 保留为 `missing_listing`。国际服小计 divine 1.5、exalted 12；腾讯服小计合成神圣石 1.5、合成崇高石 12。

`selections` 每行包含唯一 `slot`、调用方提供的 `matched_affixes` 数组及必填 `listing_id`。无匹配显式传 null，词缀必须为空；非空 ID 必须存在于本次归一化挂单中。未知 ID 是输入错误，不降级为无匹配。允许同一参考挂单用于不同槽位，每槽独立保留数据和计价。不存在的槽位不会自动补齐。

`scripts/slot_quotes.py` 的 `assemble_quotes(listings, selections, *, realm, league)` 接受 M01/M02 归一化数组，返回现有 `{context, slots}` 契约；`assemble_file(path)` 先复用 `normalize_listings` 处理原始响应，再组装。全部原始挂单均先校验，未选中的跨赛季行、上游错误、重复 ID 也会使整批失败。归一化数组的每行上下文同样必须一致。realm 仍为调用方声明的来源，不能从自编 JSON 证明真实服区。

助手通过现有汇总函数输出结果；文件、归一化或选槽失败时 stderr 报错、退出 1，无部分 JSON。组装不推断装备适用槽位、词缀匹配、最低价或查询成功状态。夹具中的槽位及词缀选择仅为自编输入，不代表实际 BD 或真实市场证据。

## 本地 BD 活动装备清单（本轮）

```sh
python3 -B scripts/assistant.py build-selections --build tests/fixtures/p02/real/build.xml --realm international --league 'Offline Test League' --response-file tests/fixtures/m01/listings.json > /tmp/m04-selections.json
python3 -B scripts/assistant.py estimate-build --from-listings /tmp/m04-selections.json
```

`build-selections` 输出可编辑清单：`build_file`、`response_file` 为绝对本地路径；`build` 记录 SHA256、活动 ItemSet、武器组和完整普通装备 inventory，`selections` 为所有活动普通槽的显式 null 选择。随后可手动填入已核对的 listing_id / matched_affixes。组装时重新读取 BD，不信任清单内缓存的 inventory。旧清单不带 build_file 时沿用原契约。

解析依据本地固定上游 `601768bd` 的 ItemsTab 保存格式、SkillsTab:GetSocketGroupWeaponSet 和 CalcSetup 主技能选择：使用 activeItemSet、activeSkillSet、Build.mainSocketGroup；主技能只启用一个武器组时覆盖 ItemSet 的界面武器组选择。保留 Swap 名称，非活动组记录在 inventory，禁止为其选价；其他 ItemSet 和物品仓库不计价。忽略 Calcs 页临时 skill_number，与 P02 mainEnv 的 MAIN 计算上下文一致。

普通装备范围为两武器、头胸手鞋、项链、两戒指、腰带、三护符、两药剂（15 个活动槽）。缺失普通 Slot 记录按上游默认 itemId=0 展开。inventory 中空槽 state=empty，非活动武器 state=inactive_weapon_set；有装备时保留 item ID 和 XML 中原始物品文本。显式清单必须恰好覆盖所有活动普通槽，漏槽、重复、非活动槽、未知 ID 均失败。空槽禁止引用挂单，汇总输出 empty_slot，既不报价也不计入 missing_slots；已装备且无引用仍为 missing_listing，不以空槽替代。

自编 P02 夹具预期：活动组 1，15 个活动普通槽，14 个 empty_slot，Weapon 2 的 Hallowed Focus 为唯一 missing_listing；小计 {}，quoted_slot_count=0。两条 Swap 库存为 inactive_weapon_set，不参与估价。双服仅复用原离线响应；手选引用不代表市场物品适用该槽或词缀匹配成功。

这是已保存普通装备的离线提取，不执行 PoB 计算。装备了 Ring 3、Arm/Leg、动态珠宝槽或 RuneSlot 时明确报错，需后续引擎 inventory 才能判断条件/天赋和插槽，不输出不完整价格；生成技能导致主技能超出已保存技能组也报错。普通装备的合法性、特殊槽禁用和物品授予技能带来的上下文变化仍需进一步引擎联调。原 BD 文件只读，未修改上游、市场或 Windows 状态。

## 按引擎生效装备整套估价

给 `build-selections` 和 `estimate-build --from-listings` 在 `--` 后附 PoB worker 命令，槽位即取自固定引擎的生效 inventory，不再静态解析 XML。未点亮天赋的 Ring 3、非活动武器组、未分配的 Arm/Leg 和仓库物品不进入选槽；Ring 3、Arm/Leg 等条件槽装备后可正常估价。未启用效果的药剂/护符（`stored_consumable`）仍是身上的装备，照常估价。不带 worker 时仍走上面的静态路径。

```sh
RUNTIME="$HOME/.local/state/poe2-assistant/p02-runtime"   # LuaJIT 与 lua-utf8 所在目录
export LUA_CPATH="$RUNTIME/?.so;;"
WORKER="python3 -B $PWD/scripts/pob_worker.py --engine /tmp/poe2-pob-source --luajit $RUNTIME/LuaJIT/src/luajit"
python3 -B scripts/assistant.py build-selections --build build.xml --realm international \
  --league 'Offline Test League' --response-file listings.json -- $WORKER > selections.json
# 在 selections.json 中为已装备槽位填 listing_id / matched_affixes，然后：
python3 -B scripts/assistant.py estimate-build --from-listings selections.json -- $WORKER
```

清单的 `build.source` 为 `engine`，`build.inventory` 保留引擎每行 state 和 stored/selected/effective ID，并附 XML 原始物品文本。估价时用同一 worker 重新读取 BD 核对选槽；引擎清单不带 worker 会报错。输出逐槽状态（`quoted`、`missing_listing`、`missing_price`、`empty_slot`）、`missing_slots` 和按通货小计。

## 引擎 inventory 状态

`scripts/pob_inventory.py` 读取固定引擎的 `pob-inventory/1` 响应。每行保留 XML 的 `stored_item_id`、引擎加载后的 `selected_item_id` 和实际生效的 `effective_item_id`，并用 `state` 区分：

| state | 含义 |
| --- | --- |
| `equipped` | 生效装备，计价 |
| `empty` | 空槽 |
| `inactive_weapon_set` | 非当前计算武器组 |
| `engine_removed` | XML 标为装备，但引擎加载时移除（如副手与双手武器冲突） |
| `engine_excluded` | 条件槽未开启（如未点亮 Ring 3 天赋） |
| `stored_consumable` | 未启用效果的药剂/护符，`effect_active=false`，仍照常估价 |

响应还附只读 `passive_spec`：引擎实际树版本、职业/升华、已加载节点及 `AdditionalRingSlot` 标记，用于解释条件槽。非活动 ItemSet 和仓库里未分配的物品不出现在任何 ID 字段。

真实引擎回归案例（`tests/fixtures/m04/inventory/` 下的自编 XML）覆盖：条件戒指槽启停、弓与箭袋、药剂/护符启停、第二武器组、双 ItemSet 切换、仓库物品、Ring 2 分配与清空。这些案例只验证引擎 inventory 判定，不代表市场或客户端行为。
