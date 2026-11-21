# 第三方声明 / Third-party notices

PoE2-Build-Assistant 建立在以下项目之上。我们对它们的改动放在各自的 fork 里（见 README“仓库关系”），每个 fork 保留原项目的 LICENSE；Windows 安装包里也随附这些许可文件。

## 以 fork 形式改造的项目（MIT）

### Path of Building Community (PoE2)

- 上游：<https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2>
- 我们的 fork：<https://github.com/Michael-crazy/PathOfBuilding-PoE2>（分支 `poe2-assistant`）
- 许可：MIT。完整许可（含 PoB 随附的 Lua、LuaJIT、libcurl 等组件许可）见 fork 中的 `LICENSE.md`。

```
Copyright (c) 2016 David Gowor

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

PoB 中文运行库（CJK 字体回退的 SimpleGraphic 等 DLL、`runtime/lua/xml.lua`）取自 [PathOfBuilding-PoE2-i18n](https://github.com/woolkingx/PathOfBuilding-PoE2-i18n) v0.1.0 发行包，其 LICENSE.md 为 PoB 的 MIT 加各运行库原有许可；随附的 Noto Sans CJK 字体按 SIL Open Font License 1.1 分发（fork 中 `runtime/SimpleGraphic/Fonts/NotoSansCJK-LICENSE.txt`）。来源与逐文件哈希记在 fork 的 `poe2-assistant/i18n-runtime.json`。

### Exiled Exchange 2

- 上游：<https://github.com/Kvan7/Exiled-Exchange-2>（源自 Awakened PoE Trade）
- 我们的 fork：<https://github.com/Michael-crazy/Exiled-Exchange-2>（分支 `poe2-assistant`）
- 许可：MIT

```
Copyright (c) 2020 Alexander Drozdov
```

（许可正文同上方 MIT 文本。）

### POBG

- 上游：<https://github.com/GGaryyy/POBG>
- 我们的 fork：<https://github.com/Michael-crazy/POBG>
- 许可：MIT

```
Copyright (c) 2026 GGaryyy
```

（许可正文同上方 MIT 文本。）POBG 自带的数据说明见其 README（数据来自 poe2db.tw、Path of Building 与 poe.ninja）。

### poe-trade2text（浏览器扩展）

- 上游：<https://github.com/intGus/poe-trade2text>
- 我们的 fork：<https://github.com/Michael-crazy/poe-trade2text>
- 许可：MIT

```
Copyright (c) 2025 Gustavo
```

（许可正文同上方 MIT 文本。）

## 随安装包分发的运行环境

- **Python**：安装包内置 CPython 3.12 官方 Windows 嵌入版（python.org），按 [Python Software Foundation License Version 2](https://docs.python.org/3/license.html) 分发；许可文件 `LICENSE.txt` 随嵌入版一起放在安装包 `python/` 目录。POBG 的 Python 依赖（如 `mcp`）按各自许可随包分发在 `pobg/lib/`，各包的许可文件保留在其 `*.dist-info` 中。
- **Electron / Chromium**：游戏内助手外壳（EE2）由 Electron 打包，包含 Chromium、Node.js 等组件。它们的许可随安装包附在助手目录的 `LICENSE.electron.txt` 与 `LICENSES.chromium.html` 中（electron-builder 自动生成）。
- **LuaJIT / lua-utf8**：由 PoB 运行时自带，许可见 PoB fork 的 `LICENSE.md`。

## 译文与数据出处

- **流放编年史 PoE2DB**（<https://poe2db.tw>）：游戏术语中英对照的唯一来源，CC BY-NC-SA 3.0，详见 [`data/DATA-LICENSE.md`](data/DATA-LICENSE.md)。
- **PoeCharm / PoeCharm2**（<https://github.com/Chuanhsing/PoeCharm>、<https://github.com/Chuanhsing/PoeCharm2>，作者 Chuanhsing）：PoB 界面文字的部分简中译法出自其翻译表。仓库未写明许可，我们注明出处并致谢。
- **PathOfBuilding-PoE2-i18n**（<https://github.com/woolkingx/PathOfBuilding-PoE2-i18n>，作者 woolkingx）：部分界面译法出自其 zh_CN / zh_TW 译文；仓库未为译文单独写明许可，我们注明出处并致谢。
- **poe.ninja**（<https://poe.ninja>）：国际服通货汇率（游戏内助手、网页预览）和 POBG 的物价数据在运行时从 poe.ninja 读取，仓库和安装包都不含其数据。请合理控制请求频率；poe.ninja 的使用条款以其网站为准。
- **官方市集数据接口**：`data/trade/` 由国际服与国服市集公开数据接口生成，见 `data/DATA-LICENSE.md`。

Path of Exile 及其游戏内容的著作权和商标属于 Grinding Gear Games。本项目是玩家社区工具，与 Grinding Gear Games 和腾讯无关，也未获其认可。
