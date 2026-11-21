# PoB 与 EE2 定制分支（U04）

我们对 PoB 和 EE2 的改动都以提交的形式放在专用分支 `poe2-assistant` 上，叠在固定的上游提交之上，跟随上游时用变基。固定值记在 `pob-branch.json` 和 `ee2.json`（`pob.json` 仍只记基线，离线索引按它核对，不要往里加字段）。

## 仓库

| | PoB | EE2 |
| --- | --- | --- |
| fork | [Michael-crazy/PathOfBuilding-PoE2](https://github.com/Michael-crazy/PathOfBuilding-PoE2) | [Michael-crazy/Exiled-Exchange-2](https://github.com/Michael-crazy/Exiled-Exchange-2) |
| 上游 | `PathOfBuildingCommunity/PathOfBuilding-PoE2`，bare 里在 `refs/remotes/upstream/*`；用户 fork 在 `fork/dev` | `Kvan7/Exiled-Exchange-2`（工作副本的 `origin`） |
| 基线 | `601768bd`（上游 `dev`，与 fork `dev` 相同） | `cca30662`（上游 `master`，Merge PR #1043） |
| 分支头 | `pob-branch.json` `head` | `ee2.json` `head`（`ed93eea9`） |

## PoB 提交序列

| 提交 | 内容 | 来源 |
| --- | --- | --- |
| P04 运行库 | i18n v0.1.0 发行 ZIP 的 DLL（除 `lua51.dll`）、CJK 回退字体和许可、`runtime/lua/xml.lua`（i18n 源码 `8cb17639`）；删除 `runtime/z.dll`；`poe2-assistant/i18n-runtime.json` 记来源、许可和每个文件的 SHA-256 | `ops/localize_pob.py` |
| P04 菜单 | 菜单和控件标签、`Start-PoB-zh-CN.cmd` / `Start-PoB-en.cmd` | `ops/localize_pob.py` |
| P07 | `EditControl` 粘贴保留有效 UTF-8 | `ops/enable_pob_unicode_paste.py` |
| P08 | 计算页标签，`src/Modules/AssistantCalcLabels.lua` | `ops/localize_pob_calcs.py` |
| U01 | `launch:OnInit` 拉起旁边的助手 | `ops/hook_pob_assistant.py` |
| U04 包模式 | 有 `poe2-assistant/package-mode.txt` 时（B03 补全，见下）不显示红色“Developer Mode active”、Dev Mode 标签和“(dev)”，不在退出时自动保存；仍保留开发模式的两点：用户数据在脚本目录、不连上游自动更新 | 直接提交 |
| U02 | `src/Modules/AssistantLiveBuild.lua`；`Build.lua` 加载模块、`OnFrame` 末尾发布、`Shutdown` 标记关闭，共 3 行 | 直接提交 |
| U06 | `src/Modules/AssistantCommands.lua` 命令通道（加入装备、后台保持跑帧）；`Build.lua` 3 行；`Common.lua` 在 `sanitiseText` 外包一层保留 CJK 文字；`AssistantSettings.lua` 一项 | 直接提交 |
| B03 | 包模式下 `devModeAlt` 恒为 false，F5/F6/Pause、Ctrl 重建缓存、Shift 复制 XML、JSON 导入、节点 ID 搜索、`DEV[...]` 帮助、后台协程报错与正式版一致；`src/Modules/AssistantBuildFixes.lua` 在 `buildMode:LoadDB` 纠正 `X Resistance is ±N%`（与 `pob_server.correct_build` 同一规则） | 直接提交 |

前五个由 `python3 -B ops/pob_branch.py migrate` 一次生成（固定作者和日期，可复现）。之后分支就是唯一来源：**新改动直接作为提交加在分支上，不再写安装脚本**。旧脚本保留作回归：在分支上重放必须不产生任何改动。

二进制第三方文件直接提交（上游自己也把 `runtime/*.dll` 放在仓库里），来源写进 `poe2-assistant/*.json`，`ops/pob_branch.py verify-runtime` 对照固定 ZIP 逐个核对。上游更新 DLL 时变基会在这些文件上冲突，这是有意的：需要重新确认 i18n 运行库和新 SimpleGraphic 是否兼容。

## 新补丁怎么加（U02 / P03 / U03 …）

1. 在工作副本从 `poe2-assistant` 开始改，一个任务一个或几个小提交，标题 `<任务号>: <做了什么>`（英文），提交署名见 [CONTRIBUTING.md](../CONTRIBUTING.md)。
2. 改动集中：新逻辑放新文件（`src/Modules/Assistant*.lua`，数据和说明放 `poe2-assistant/`），上游文件只改调用点的少数几行；不重排、不格式化上游代码；保持 LF；不提交用户状态（`src/Builds`、`Settings.xml`、`*.cfg` 已被上游忽略）。
3. 中文只来自 PoE2DB 数据（P03 的 `data/terms/pob-localization/`），生成的数据文件和生成它的项目脚本提交号一起写进 `poe2-assistant/`。
4. 跑 `python3 -B ops/rebase_check.py --work <临时目录> --skip-ee2 --pob-suite`（见下），全部通过后推送 `poe2-assistant`（经 PR），再把新的分支头写进 `pob-branch.json` 的 `head`（试算引擎只接受固定提交或这个分支头），和项目改动一起提交。
5. 如果新补丁有意改动了旧脚本也改的位置，重放检查会失败：在 `rebase_check.py` 里去掉对应脚本的重放并在提交说明里写明。

## 变基检查

`python3 -B ops/rebase_check.py --work <临时目录> [--fetch] [--pob-onto upstream/dev] [--ee2-onto upstream/master] [--pob-suite]`

在临时目录克隆两个 fork 仓库，把分支从基线变基到指定上游提交。有冲突就报告冲突的提交和文件并放弃变基；EE2 只有 `renderer/package-lock.json` 冲突时，取上游的锁文件并用 `npm install --package-lock-only` 重新生成。主仓库和分支不会被修改。

变基成功后的检查：
- PoB：旧安装脚本重放无改动、i18n 运行库核对、改动过的 Lua 能编译、`ops/check_pob_unicode_paste.lua`（P07）、`ops/test_hook_pob_assistant.py`、真实引擎 `test_pob_server`；`--pob-suite` 再以变基后的树为 `POB_ENGINE` 跑全部 `scripts/test_*.py`。
- EE2：`main` 和 `renderer` 各自 `npm ci`，`tsc --noEmit` / `vue-tsc --noEmit`、`eslint`、`prettier --check src`。

结果写 `<临时目录>/report.json`，全部通过退出码为 0。我们仍停在固定版本；真正升级时在工作副本做同样的变基，旧分支头打标签保留，更新 `pob.json` 的 `commit`、`pob-branch.json` / `ee2.json` 的 `base` 和 `head`（改基线还要重建离线索引）。

## EE2 分支

`poe2-assistant` 已经是 `cca30662` 上的线性提交（9 个），没有合并上游的提交，因此不改写历史（U01 包的 `版本.json` 引用 `ed93eea9`）。第一个提交只重新生成 `renderer/package-lock.json`（Node 22），变基时由检查脚本自动处理；其余是助手功能。新改动同样直接加提交。

## 打包

正式包应直接用分支导出（`git archive poe2-assistant`）作为 PoB 目录，保留 `poe2-assistant/package-mode.txt`，`.pob-commit` 写分支头。`ops/build_u01_package.py` 目前仍从旧的安装脚本重放目录复制 PoB 并现场装钩子，之后改为分支导出。
