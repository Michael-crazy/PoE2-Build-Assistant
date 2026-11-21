# P02 · Windows 数值对照（待执行）

本检查点只准备样本及 Linux 重放，Windows 未验收。使用 runner 提交本检查点后
的 `task/P02` 版本，记录实际提交 SHA。固定 PoB fork 为
`601768bd105869618c3d6581b883e5d7aeec91b2`（来源 `sources/pob.json`），
不能用自动更新后的版本替代。开发源码检出的启动布局见 `sources/pob-runtime.md`。
这批输入由本项目编写并经固定上游序列化，不含玩家账号、角色或在线导入资料。

## 预检与输入

在助手仓库根目录运行 PowerShell：

```powershell
git rev-parse HEAD
$fixture = 'tests/fixtures/p02/real'
$expected = Get-Content "$fixture/expected.json" -Raw | ConvertFrom-Json
$expected.inputs_sha256.psobject.Properties | ForEach-Object {
    $actual = (Get-FileHash "$fixture/$($_.Name)" -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $_.Value) { throw "Input hash mismatch: $($_.Name)" }
    "$($_.Name): $actual"
}
# 替换为 Windows 固定引擎检出目录，HEAD 必须匹配且 status 无输出。
git -C C:\work\PathOfBuilding-PoE2 rev-parse HEAD
git -C C:\work\PathOfBuilding-PoE2 status --porcelain
```

输入应保持 LF；仓库 `.gitattributes` 已限定这些夹具。哈希不符时停止对照，保留差异。
打开本目录 `build.xml`（在构筑列表导入本地 XML，或将副本放入 PoB 的 Builds 目录后打开）。
等待计算完成；不要从 XML 的 `<PlayerStat>` 缓存读结果：其中 Life=1187 是生成时旧缓存，
此次真实重算基准为 65。若界面重算后不为 65，记录差异并判为未通过，不手改预期。

确认 Ranger、等级 1（原文件 Auto 模式）、无升华、无额外分配天赋；技能组 1 的
Fireball 20/0、主活动技能 1；装备组 Default/1、武器组 1；配置组 1 保持原样，
没有自定义配置 Input，保留默认占位值。基准主手为空、副手 P02 Focus / Hallowed Focus，157 ES。
技能对两组均启用，仍须保持当前武器组 1。等级不足需求是本受控样本的既有状态，勿调整等级。

## 对照顺序

每行都从重新打开的原 `build.xml` 开始，避免上一个候选残留。Items 中粘贴完整候选文本，
明确装备到活动主手 `Weapon 1`；不要依赖添加物品后的自动选槽。不要保存原文件。

| 阶段 | 输入/槽 | CombinedDPS | Life | EnergyShield | Armour | Evasion |
|---|---|---:|---:|---:|---:|---:|
| 基准 | 原 BD | 124.92202899364 | 65 | 157 | 0 | 7 |
| 法杖 | wand.txt / Weapon 1 | 124.92202899364 | 65 | 257 | 0 | 7 |
| 弓 | bow.txt / Weapon 1 | 124.92202899364 | 65 | 0 | 0 | 7 |
| 恢复 | 丢弃修改，重开原 BD | 124.92202899364 | 65 | 157 | 0 | 7 |

法杖 ES 差值 +100，弓 -157，其余四项差值均 0。法杖保留副手；双手弓应移除副手。
DPS 比较选中 Fireball 的 **CombinedDPS**（含 Ignite），不是 TotalDPS=124.83333333333，
也不是 FullDPS。Calcs 中核对选中技能的伤害及防御；若侧栏显示综合 DPS，记录其实际标签。
记录界面显示字符串与舍入精度，预期值按相同精度舍入后应相等；整数防御项须完全一致。
如果界面没有直接显示 CombinedDPS，保留 Total DPS 与 Ignite DPS 的明细截图供核对，
不要把不同口径直接标为通过。机器原始预期及精确请求摘要见 `expected.json`。

`bow.txt / Weapon 1 Swap` 是后台 worker 拒绝用例：预期 `slot outside calculated weapon set`，
非零退出且无指标。它由 Linux 重放验证，不是要求 PoB 界面禁止编辑非活动组；
Windows GUI 数值对照只比较上表的活动组。Windows worker 平台适配不属于本检查点。

## 验证回执

- 状态：pending / pass / fail；日期、Windows 版本、助手提交、引擎 HEAD/干净状态。
- 输入哈希检查输出；实际启动 EXE 路径和版本；任何初始化提示。
- 主技能/等级/配置组/装备组/武器组截图路径。
- 基准、法杖、弓、恢复各五项显示值、标签/舍入精度及截图路径。
- 法杖保留副手、弓移除副手；丢弃修改重开后的恢复结果。
- 再运行上述输入哈希检查，记录原 BD 与候选未变；失败时写实际/预期差异。

Linux 重放：用真实引擎测试（见 `README.md`）。它校验所有输入哈希、
成功请求摘要、两例的 baseline/replacement/delta 全五项（浮点容差 1e-12）及非活动组拒绝，
并验证引擎全部文件和输入在运行前后未变。Windows UI 结果不能由这份 Linux 报告代替。
确认后保存、关闭重开另存 BD，以及双服/网络隔离等验收仍留后续检查点。
