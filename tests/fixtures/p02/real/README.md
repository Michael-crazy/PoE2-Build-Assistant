# P02 真实引擎样本

`build.xml` 由固定 PoB `601768bd105869618c3d6581b883e5d7aeec91b2` 的
`HeadlessWrapper.lua` 在独立源码副本中生成。它是受控回归 BD，不是玩家终局配装。
Ranger 等级 1，Fireball 20/0 为主技能组 1，武器组 1，副手 Hallowed Focus 提供
157 ES（基础 57 + 词缀 100）；无自定义配置或已分配天赋。基准 DPS 为当前技能的 CombinedDPS。

生成操作复用上游测试的接口：

```lua
dofile('HeadlessWrapper.lua')
newBuild()
build.skillsTab:PasteSocketGroup('Fireball 20/0  1')
build.mainSocketGroup = 1
build.itemsTab:CreateDisplayItemFromRaw('Rarity: Rare\nP02 Focus\nHallowed Focus\n+100 to maximum Energy Shield')
build.itemsTab:AddDisplayItem()
runCallback('OnFrame')
-- 仅夹具生成阶段序列化；trial worker 不保存。
local xml = assert(build:SaveDB('P02 generated trial'))
```

`wand.txt` 在主手增加 100 ES；`bow.txt` 为双手 Gemini Bow，活动主手试穿应移除副手。
错误地指定非活动 `Weapon 1 Swap` 曾导致副手也被移除，修复后拒绝该请求。

Linux 真实引擎回归由 `scripts/test_pob_server.py` 等测试在设置 `POB_ENGINE` 后运行（引擎与 runtime 见
`sources/pob-user-runtime.md`），并核对输入/引擎文件前后哈希。
此样本尚未做 Windows 界面数值对照或网络隔离验收；原有上层目录 synthetic 样本仍仅用于协议测试。

## 可保留的输入与 Windows 复现

本目录为项目编写的受控测试输入；没有复制玩家 BD。物品名、基底名和技能 ID
由固定上游数据识别，XML 使用上游序列化格式；上游源码及许可仍随固定引擎检出提供，
本目录不打包引擎或第三方运行时。生成接口来源为固定引擎
`src/HeadlessWrapper.lua` 与 `spec/System/TestMiscCalculator_spec.lua`。
以上生成片段解释来源，不要求重新生成相同字节：序列化缓存可能随帧时序变化，
精确重放应直接使用已入库的 XML/txt，并核对 `expected.json` 的 SHA256。

`expected.json` 固定前轮真实 Linux 响应的全五项 baseline/replacement/delta、
候选槽位及请求摘要；它不是每次运行动态生成的预期。回归对照它，
而不是只检查 ES。Windows 按 [WINDOWS.md](WINDOWS.md) 逐项记录界面、舍入、
副手变化、恢复与源文件哈希；当前仍待 Windows 验证。
