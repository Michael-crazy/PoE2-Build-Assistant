# 发布布局与 PoB 内更新（R02）

正式包用 PoB 自带的更新器更新自己（PoB 和助手走同一套机制，不做回退）。打包：`ops/build_u01_package.py`；发布：`.github/workflows/release.yml`（R04）。

## 包布局

```text
PoE2助手/
  启动中文PoB.cmd  显示MCP配置.cmd  使用说明.txt      内容稳定，不进 manifest
  PoB/                官方便携版布局：仓库 src/、runtime/ 与根目录 changelog.txt、help.txt、LICENSE.md 平铺
    manifest.xml      <Version number="0.1.0" platform="win32" branch="assistant-release">
    poe2-assistant/   包模式标记、术语表（PoB 分支）
    assistant-app/    EE2（不叫 assistant/：PoB 把实时 BD、WeGame 导入放在 <用户目录>/Assistant，Windows 不分大小写）
    backend/ python/ pobg/ licenses/ 版本.json 使用说明.txt
    Builds/ Settings.xml MCP配置.txt Assistant/ ...   玩家数据，不进 manifest，更新不碰
```

`GetScriptPath()==GetRuntimePath()` 且 manifest 带 `branch`/`platform`：PoB 不是开发模式、启动时后台检查更新，用户数据在程序旁边（便携模式）。官方 `PathOfBuilding-Installer` 是私有仓库，布局照官方便携 ZIP 的实际内容自己生成。比官方多带 `HeadlessWrapper.lua`、`_SimpleGraphic.def.lua`（后端无头引擎用）；`Update.exe`、`msvcr100.dll` 同官方不进 manifest（更新时它们正在运行）。

## manifest 的 part

| part | 内容 | 下载地址 | 替换时机 |
| --- | --- | --- | --- |
| default / program / tree | 根目录文件、脚本和数据、天赋树 | 发布分支 | PoB 运行中（普通模式） |
| runtime | exe、DLL、`lua/`、字体 | 发布分支 | PoB 退出后由 `Update.exe` |
| backend | `backend/`、POBG 源码、文档、`版本.json`、`assistant-app/assistant-backend.json` | 发布分支 | 普通模式 |
| python | `python/`、`pobg/lib/`（含 DLL/pyd） | 发布分支 | PoB 退出后 |
| assistant | EE2（主程序 205 MB） | Release 资产 `assistant-<EE2 提交前12位>.zip` | PoB 退出后 |

发布分支：PoB fork 的 `assistant-release`（`https://raw.githubusercontent.com/Michael-crazy/PathOfBuilding-PoE2/{branch}/`），内容是 `PoB/` 除 `assistant-app/` EE2 文件外的全部登记文件，文件名中的空格写成 `{space}`（与官方相同），`.gitattributes` 为 `* -text`。助手 zip 只在 EE2 提交变化时重建，后续版本的 manifest 继续指向旧 Release 的资产。

## 对 PoB 的改动（`UpdateCheck.lua` / `UpdateApply.lua`，PoB 分支）

- 两个下载函数加 `OPT_FOLLOWLOCATION`：Release 下载地址 302 跳转。
- `assistant`、`python` part 与 `runtime` 一样走 basic 模式：运行中的助手和后端占着 exe/DLL，普通模式在 PoB 进程里替换会卡住。
- `Update.exe` 内嵌原版 Lua 5.1（ANSI 路径），中文安装路径下打不开绝对路径：给它的操作改用相对程序目录的路径（它本来就在程序目录运行）。上游装在中文路径下也有同样问题。
- PoB 的 `lzip` 模块同样只认 ANSI 路径，打不开时直接让进程崩溃：先用 Lua 的 `io.open`（PoB 的 LuaJIT 打过宽字符补丁）确认，再用相对路径 `Update/<zip>` 打开；打不开只下载一次。
- `UpdateApply.lua` 等待被占用文件改为最多约 60 秒；没替换成功的文件下次检查时 sha1 不符，自动重新下载。

## 版本号

唯一来源是 `release/changelog.txt` 顶部的 `VERSION[x.y.z][yyyy/mm/dd]`（PoB 更新弹窗按这个格式列出新版本的更新内容，包里的 `changelog.txt` 是它加上游 PoB 的 changelog）。tag `v0.1.0` → manifest `number="0.1.0"`、`PoE2助手-v0.1.0.zip`、`版本.json` 的 `version`、PoB 左下“版本：0.1.0”。

## 已知限制

- 每次检查更新都对全部登记文件重算 sha1（PoB 自带的纯 Lua 实现，约 63 MB/s），约 960 MB，后台线程约 14 秒。
- 更新 Python 或 POBG 依赖时，开着的 AI 客户端占着 POBG 的 python.exe/pyd，这些文件等 60 秒后跳过，关掉客户端后下次检查补上。
- 包路径不能太深：`assistant-app/` 下最深的相对路径约 140 个字符，加上解压位置不能超过 Windows 260 字符上限。
