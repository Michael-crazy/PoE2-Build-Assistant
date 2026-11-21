PoE2 助手 v{version}（{date}）：简体中文 Path of Building（PoE2）+ 游戏内装备评估浮层 + AI 问 BD（MCP）。

## 本版本

{changes}

{assistant}

## 功能

- **中文 PoB**：基于 Path of Building Community（PoE2）开发版，界面、技能、天赋、装备词缀为简体中文（国服译名）。
- **游戏内助手**：鼠标指向背包、仓库或市集里的装备，按 `Ctrl+Shift+D`，按 PoB 当前打开的 BD 评估这件装备（DPS、生命、抗性等变化），支持国际服和腾讯服；查价与性价比。
- **AI 问 BD**：自带 POBG（MCP 服务），在 Claude、Cursor、Cherry Studio 等客户端里用中文问技能、天赋、词缀，或让它算你 PoB 里当前 BD 的数据。
- **自动更新**：PoB 启动时在后台检查更新，只下载改动的文件；你的 BD 和设置不受影响。

## 安装

1. 下载下面的 `PoE2助手-v{version}.zip`，解压到一个普通文件夹（如 `D:\Games\`）。不要放在 `C:\Program Files` 这类需要管理员权限的位置，否则无法自动更新；路径也不要太深。
2. 双击 `PoE2助手\启动中文PoB.cmd`。PoB 以中文打开，游戏内助手在后台启动（托盘图标）。
3. 在 PoB 里导入或打开你的 BD，进游戏指向装备按 `Ctrl+Shift+D`。
4. 想在 AI 客户端里用，双击 `显示MCP配置.cmd`，照着加一次配置。

详细说明见包里的 `使用说明.txt`。自带 Python，不需要另装任何东西。

## 首次运行的提示

- **“Windows 已保护你的电脑”**：程序没有代码签名证书，第一次运行时 Windows SmartScreen 可能拦截。点“更多信息”→“仍要运行”。
- **杀毒软件误报**：助手需要读取剪贴板、注册全局快捷键、在游戏上方显示浮层，个别杀毒软件可能误报。可以把解压目录加入信任；源码全部公开在本仓库和下面几个 fork 里，可以自行构建核对。
- **腾讯服**：读取腾讯服客户端时可能需要管理员权限，助手会提示并经 UAC 以管理员重启。

## 更新

- PoB 左下角出现“更新已就绪”时点它，再点“更新”。PoB 会关闭、替换文件后自动重新打开；左下角显示当前版本号。
- 也可以点左下角“检查更新”手动检查。
- 只改了 PoB 时只下载改动的文件；助手有新版本时会额外下载一个约 150 MB 的文件。

## 已知问题

- 第一次检查更新要校验全部文件，后台约十几秒，期间“检查更新”按钮显示进度。
- 如果 AI 客户端正开着 POBG，更新 Python 或 POBG 依赖时对应文件会跳过，关掉客户端后下次检查自动补上。
- 文件夹放在中文路径下可以正常使用和更新；但整个路径太长（超过 Windows 260 字符限制）时解压会失败，请放浅一点。
- 助手的设置和日志在 `%APPDATA%\exiled-exchange-2`，与原版 Exiled Exchange 2 共用。

## 来源与许可

- 本项目代码：MIT。编年史（poe2db.tw）数据：CC BY-NC-SA，仅限非商业使用。
- Path of Building Community（PoE2）、Exiled Exchange 2、POBG 均为 MIT，我们的改动在各自 fork 的 `poe2-assistant` 分支：
  [PathOfBuilding-PoE2](https://github.com/Michael-crazy/PathOfBuilding-PoE2)、[Exiled-Exchange-2](https://github.com/Michael-crazy/Exiled-Exchange-2)、[POBG](https://github.com/Michael-crazy/POBG)。
- 第三方组件许可见包里的 `PoB\licenses\` 和仓库的 [THIRD-PARTY-NOTICES.md](https://github.com/Michael-crazy/PoE2-Build-Assistant/blob/main/THIRD-PARTY-NOTICES.md)。

## 校验

```
{checksums}
```
