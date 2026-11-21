# 固定 PoB 版本的运行布局

以下来自本地检出的 `601768bd105869618c3d6581b883e5d7aeec91b2`，尚未运行真实 Windows 客户端。

- `CONTRIBUTING.md:55–71` 说明开发检出可直接用 `runtime/Path{space}of{space}Building-PoE2.exe` 启动；文件名中的 `{space}` 是实际字符。Linux 运行它需要 Wine。
- `runtime/` 随 Git 提供 Windows EXE、`SimpleGraphic.dll`、`lua51.dll`、其他 DLL、字体和 `lua/` 模块；`src/Launch.lua` 为程序脚本入口。不要只复制 EXE 后当成完整安装。
- `src/Launch.lua:47–60` 从当前或父目录读取 manifest；识别源码模式后启用 devMode。非 devMode 会检查更新，`first.run` 也会触发安装更新。本轮入口不更改这些上游行为。
- `RELEASE.md` 的 Installer creation 与 `.github/workflows/installer.yml` 使用独立 `PathOfBuilding-Installer` 仓库、Python、NSIS 构建发行包；源码检出不等于已生成便携包。本检查点未构建或发布。

## P02 后台试穿可行性线索（未开始实现或验收）

- `src/HeadlessWrapper.lua` 加载 `_SimpleGraphic.def.lua`、`Launch.lua` 并调用 `OnInit` / `OnFrame`；暴露 `newBuild()`、`loadBuildFromXML(xmlText, name)` 和 `build`。可从本地 XML 加载，避免在线角色导入。
- `.busted` 设置工作目录 `src`、helper `HeadlessWrapper.lua`、Lua 路径 `../runtime/lua/?.lua;../runtime/lua/?/init.lua`；`.github/workflows/test.yml` 在 Linux 容器用 `busted --lua=luajit`。`Dockerfile` 列出 LuaJIT、busted、luautf8 等依赖，可复用其环境，而非迁移计算代码。
- `src/Classes/CalcsTab.lua:729` 的 `GetMiscCalculator()` 返回计算函数及基准。`spec/System/TestMiscCalculator_spec.lua` 用 `calcFunc({ repSlotName = "Weapon 1", repItem = item })` 检验替换武器的护盾结果；候选可由 `new("Item"):Item(rawText)` 构造，优先走此覆写路径。
- `src/Modules/CalcSetup.lua:1221` 起处理替换槽、双手武器与副手例外；不要在助手重写槽位规则。`spec/System/TestItemsTab_spec.lua` 另覆盖技能指定武器组，P02 必须保持主技能、配置和武器组一致。
- 下一步先在隔离进程跑上述 MiscCalculator spec，再用可分发 XML 做基准/覆写/原 BD 未变的验证，对照 `build.calcsTab.mainOutput` 和界面指标，明确主技能 DPS 与 Full DPS 的区别。保存仍应是独立确认动作。
- 本机未发现 `luajit` 或 `busted`，本轮未安装依赖或运行 PoB Lua 测试；以上是源码证据，不是后台试算已通过。Wrapper 对 `lcurl.safe` 做跳过、部分图形/子脚本 API 为桩，初始化报错会 `io.read`；后续 worker 需捕获启动失败并设超时，验证离线启动及无 BD 写回。

P02 已完成一轮离线进程契约夹具检查点；已编写尚未通过引擎验证的真实 worker；runtime 先决条件与 Windows 对照步骤见 [pob-trial-contract.md](pob-trial-contract.md)，上述源码复用线索尚未经过真实计算验证。
