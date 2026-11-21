# P06 最小导出检查点

固定引擎见 `pob.json`：601768bd105869618c3d6581b883e5d7aeec91b2。
直接复用 `src/Modules/BuildExportPoE2.lua`，不复制、修改导出算法或上游代码。
`src/Export/Scripts/buildplanner.lua` 是从 DAT 生成槽位映射的开发工具，不是 BD 导出入口。
用户界面已有 Import/Export → Export Selected Sets / Export All Loadouts。

`scripts/pob_export.lua` 是供已加载 BD 的 PoB Lua 环境调用的模块，本检查点未增加 CLI 或 UI 接线：

```lua
local exporter = dofile('/absolute/path/to/scripts/pob_export.lua')
local path, err = exporter.write(build, '/existing/output/leveling.build', {
    name = '开荒', author = '作者', description = '备注', useGeneratedItemText = false,
}, {specIndex = 1, skillSetId = 1, itemSetId = 1})
assert(path, err)
```

为终局再次调用，显式选择对应三套 ID 和不同文件路径。`specIndex` 是树列表索引，其他两项是集合 ID。
输出目录必须已存在，文件存在时会覆盖。未选择或集合不存在时，在打开文件前拒绝。
适配器返回写入/关闭失败；文件写入不具备事务性，失败后应删除不完整文件再重试。

精确运行依赖：PoB 定制 LuaJIT 提交 `2460b3ff93a1c955de3d62cfc825de7d68dc272e`；
固定引擎自带 dkjson 2.5（MIT），库存映射 `src/Data/InventorySlots.lua`（GGG 数据）。
LuaJIT 可解析上游 `continue` / `?.` 扩展；普通 Lua/LuaJIT 不能视为替代品。
本检查点独立测试不需要 busted、luautf8、GUI、游戏或完整引擎初始化。
生成装备文本额外依赖引擎 `colorCodes`、`colorCodeToMarkupColour`、`itemLib.formatModLine` 和完整 Item 对象；未验证此路径。
缺少 gem gameId 时上游通过 `ConPrintf` 记录并跳过；适配器未把跳过改成失败。
完整真实 BD 初始化还需 P02 runtime，不能据此测试声称已完成。

源码 SHA-256：
- BuildExportPoE2.lua：`1581790b106d658ebab9d75ca5e51da3ae32603e9f622b96dc7270413eeb4152`
- dkjson.lua：`d6ea5c4d576e42f7ae87fe0339707e4c5b73222e3f9890eaa4edcd6f4b8783b6`
- InventorySlots.lua：`b5acdb83dc79e81047131c12281617a8527830a9814abbcd7ca0921197ea15e4`

文件为 UTF-8 JSON，没有 XML、压缩或 base64 封装。测试实际读取上游编码结果，核对
`name/author/description`、`passives[{id,weapon_set,additional_text}]`、
`skills[{id,additional_text,support_skills}]` 与 `inventory_slots[{inventory_id,slot_x,additional_text}]`；
空集合编码为 `[]`。支援技能可为 ID 字符串或带备注的对象。
装备输出是槽位教学备注/生成文本，上游当前不会导出完整稀有装备词缀对象；技能等级/品质也是文本提示。
这里核对固定上游格式，不代表验证游戏官方 schema 或客户端接受。

复现：`python3 -B -m unittest discover -s scripts -p 'test_*.py' -v`。
独立测试可用 `POB_EXPORT_ENGINE` / `POB_EXPORT_LUA` 指定引擎和解释器路径；缺少依赖会显示 skipped。
测试核对引擎 HEAD/工作树，运行真实上游模块及 dkjson；输入是自编 Lua 对象与测试 ID，非真实角色样本。
下一步用真实 BD 的开荒/终局集合验证完整环境，再由 Windows 两服加载并核对天赋、技能、槽位备注与中文显示。
