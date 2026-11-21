# 助手外壳与 Python 后端接口 v1

外壳是改造后的 Exiled Exchange 2（EE2），源码在 fork [Michael-crazy/Exiled-Exchange-2](https://github.com/Michael-crazy/Exiled-Exchange-2) 的 `poe2-assistant` 分支（见 [pob-branch.md](pob-branch.md)）。

构建（Node 22）：`cd renderer && npm install && npm run make-index-files && npm run build`，再 `cd ../main && npm install && npm run build && npx electron-builder build --win dir --x64 -c.win.signAndEditExecutable=false --publish never`，产物在 `main/dist/win-unpacked`。

## 自动识别当前游戏

主进程用一个常驻 PowerShell 每 2 秒查一次进程（`main/src/host-files/GameDetector.ts`），按进程名判断服务器：

| 进程 | 服务器 `realm` | 窗口标题 | 游戏配置（`文档\My Games\Path of Exile 2\`） | 语言 |
|---|---|---|---|---|
| `PathOfExile.exe`、`PathOfExileSteam.exe` | `pc-ggg` | `Path of Exile 2` | `poe2_production_Config.ini` | 读该配置 `[LANGUAGE] language=`，`zh-TW` → `cmn-Hant`，缺省为 `en` |
| `PathOfExile_x64.exe` | `pc-tencent` | `流放之路：降临` | `poe2_production_tc_Config.ini` | `cmn-Hans` |

- 日志取游戏程序所在目录的 `logs\Client.txt`。程序路径用 `QueryFullProcessImageName`（受限查询权限）读取，游戏以管理员运行时也能读到。
- 设置里的窗口标题、日志、游戏配置留空表示自动；用户填写的值优先。旧配置升级到 v36 时，默认标题 `Path of Exile 2` 改为空。
- “跟随当前游戏”（`followGame`，默认开）打开时，EE2 的服务器和语言随游戏切换。EE2 没有简中数据：腾讯服时 EE2 的数据语言设为英文（`Ctrl+D` 查价先经后端 `translate-item` 把简中装备转成英文），界面用简体中文（`cmn-Hans`，M02/M03）；后端收到的 `game.language` 是 `cmn-Hans`。
- 原生窗口挂接一个进程只能启动一次。已挂接一个服后又检测到另一个服，助手以相同权限自动重启并挂接新窗口。
- 游戏以管理员运行而助手不是时，弹窗提供“以管理员身份重启助手”，点后弹出系统 UAC 确认。没有改成每次启动自动提权：国际服不需要管理员，提权总要用户点 UAC。

## 后端进程

- 启动配置：可执行文件同目录的 `assistant-backend.json`，或环境变量 `POE2_ASSISTANT_BACKEND_CONFIG` 指定的文件。相对路径以该文件所在目录为基准：

  ```json
  {"command": "python.exe", "args": ["-B", "backend/assistant_shell_stub.py"], "cwd": "."}
  ```

- 助手启动时即拉起后端并常驻；后端退出后，下一次请求时重新拉起。环境变量加 `PYTHONUTF8=1`。
- stdin/stdout 都是 UTF-8 JSON 行，一行一条。stdout 只能写响应，日志写 stderr（外壳记入 EE2 日志）。
- 请求：`{"protocol": "assistant-shell/1", "id": 7, "method": "evaluate-item", "params": {...}}`。`id` 为整数，外壳保证不重复。
- 响应：`{"id": 7, "result": {...}}` 或 `{"id": 7, "error": {"code": "...", "message": "..."}}`。`message` 直接显示给用户，用简体中文。
- 外壳单次请求等 30 秒。超时就结束并重新拉起后端，避免卡住的后端让后续请求全部超时。
- 任何失败都在浮层里用中文显示原因，不静默。外壳自身错误码：`backend-unavailable`（配置缺失或无法读取）、`backend-exited`（后端退出，下一次请求重新拉起）、`backend-timeout`、`no-item-copied`（按键后 0.5 秒内剪贴板没变化：已穿戴的装备无法复制，或鼠标不在装备上）、`clipboard-not-item`（剪贴板变了但不是装备文本）、`empty-result`（响应既无 `result` 也无 `error`）、`shell-timeout`（浮层 40 秒没收到主进程回复）。这两种复制失败在 `Ctrl+D` 查价窗口里也显示同样的中文说明。每次请求在 EE2 调试日志（设置 → 调试）记一行方法、结果码和耗时。

## `evaluate-item`

快捷键默认 `Ctrl+Shift+D`（设置 → 快捷键 → 装备评估，可改）。外壳按游戏的“显示词缀”键复制鼠标所指装备，发出：

```json
{"item_text": "物品类别: 手套\n...", "game": {"realm": "pc-tencent", "language": "cmn-Hans"}}
```

- `item_text`：游戏剪贴板原文（高级描述，含词缀名和等阶）。
- `game.realm`：`pc-ggg` 或 `pc-tencent`；未检测到游戏时取设置里的服务器。`game.language`：上表的语言，未检测到为 `null`。

桩程序 `scripts/assistant_shell_stub.py` 返回收到的服务器、语言和前几行原文。

`scripts/assistant_backend.py` 的 `result` 包含试算契约的 `build`、`skill`、`baseline`、`slots`、`reloaded`（见 [试算契约](pob-trial-contract.md)），以及 `item`（`language`、`rarity`、`item_class`、`base`、`unique`、`unrecognized`、`pob_text`）和 `timing_ms`。下面这些派生值是给 M07 浮层直接显示的，浮层不需要再计算：

- `item.name`：剪贴板里的装备名原文（稀有名、传奇名或魔法/普通装备的整行）。`item.base_name`、`item.unique_name`：基底和传奇在客户端语言下的名称，来自 `data/terms/poe2db-1.0`（腾讯服简中，国际服繁中客户端繁中，其他英文）；不是传奇时 `unique_name` 为 `null`，表里没有时用英文。
- `item.price`：市集“复制”带出的价格备注（`Note: ~b/o 5 exalted`，繁中 `備註:`、简中 `备注:`），没有时为 `null`。形如 `{"kind": "buyout", "amount": 5, "currency": "exalted", "currency_name": "崇高石"}`：`kind` 为 `buyout`（`~b/o` 一口价）或 `price`（`~price` 标价）；`amount` 为数字（`1/2` 记 0.5）；`currency` 为备注里的通货代号；`currency_name` 为客户端语言的通货名，来自 `data/terms/poe2db-1.0/stackable_currency.json`，表里没有这个代号时为 `null`，浮层这时显示 `currency` 原文。备注行不进 `pob_text`，也不算未识别行。
- `build.source`：`live` 表示用的是 PoB 正在打开的 BD（`build.unsaved` 为真时含未保存的修改，`build.path` 可能为 `null`）；`window`/`settings` 表示 PoB 没开或没打开 BD，用的是 BD 文件；`explicit` 是启动时固定的 BD。
- `build.corrected_lines`：加载 BD 时自动纠正的抗性行数（导入错误的 `X Resistance is ±N%`：导入工具把 `-10% to Fire Resistance` 误写成 `Fire Resistance is -10%` 时，PoB 会当成“火抗固定为 -10%”）；大于 0 时浮层应提示“已自动纠正 BD 中 N 行抗性写法”。
- `skill.main_skill_name`、`skill.minion_skill_name`：主技能和召唤物技能在客户端语言下的名称；宝石表里没有时用英文，没有召唤物时为 `null`。
- `default_slot`：DPS 提升最大的槽位名；DPS 相同时取有效生命提升大的，再相同取靠前的。没有槽位时为 `null`。
- 每个槽位另有：
  - `label`：中文槽位名，如 `武器 1`、`副武器组 1`、`戒指 2`、`胸甲`；珠宝插槽按返回顺序为 `珠宝槽 1..n`。
  - `dps`：`{before, after, absolute, percent}`。`percent` 保留一位小数；基准 DPS 为 0 时为 `null`，只看 `absolute`。
  - `resists`：`Fire`、`Cold`、`Lightning`、`Chaos` 各一项 `{label, before, value, change, max, total, overcap}`。`value` 是换上后的生效抗性，`max` 是引擎算出的上限（含提高上限的词缀），`total` 是未封顶总值，`overcap = max(0, total - max)`。
  - `attribute_gaps`：`Str`、`Dex`、`Int` 各一项 `{label, required, before, after}`，`before`、`after` 是换装前后的属性缺口。
  - `displaced` 的每一项另有 `label`：被挤掉装备所在槽位的中文名。
  - `summary`：一句中文总结，例如 `比当前戒指 2 弱：DPS -97.8%，魔力 +114，火抗 -15，属性缺口 智慧 +30`。强弱看 DPS；DPS 不变时看有效生命，两者都不变时写“与当前…相当”。之后依次列出前两项有变化的有效生命、生命、能量护盾、魔力、四抗，以及这次换装新增或扩大的属性缺口。原槽位为空时写“空的…”。
- 每个槽位的 `metrics` 还带有引擎输出的 `resists`（`{value, max, total, overcap}`），`delta` 不变。

## `add-to-pob`（U06）

快捷键默认 `Ctrl+Shift+A`（助手配置 `assistant-eval` 小部件的 `addToPobHotkey`，PoB 选项“助手”组可改）。外壳先按游戏的复制键复制鼠标所指装备；0.5 秒内没复制到装备时，改用按键前剪贴板里已有的装备文本（市集“复制”），并把它放回剪贴板。参数与 `evaluate-item` 相同（`item_text`、`game`）。后端用 P05 解析，经 [PoB 命令通道](pob-trial-contract.md) 加入 PoB 当前 BD 的装备列表，不穿上、不保存。

- `result`：`status`（`added` / `exists`）、`name`（剪贴板里的装备名原文）、`message`（浮层直接显示：`已加入 PoB：<名称>` / `已存在：<名称>`）、`pob_pid`、`item_id`（PoB 里的装备号）、`unrecognized`。
- 错误码：`pob-not-running`（“PoB 未运行，无法加入”）、`pob-no-build`（PoB 停在 BD 列表）、`pob-timeout`、`not-equippable`、`unknown-base`（PoB 不认识基底）、`add-failed`，以及 `bad-request`、`parse-failed`。
- 浮层：不抢游戏焦点，在 `assistant-eval` 位置显示一行提示（标题“加入 PoB”），成功 2.5 秒、失败 5 秒后自动隐藏。鼠标没指着装备、剪贴板里也没有装备时提示“没有可加入的装备……”。

## `web-preview`（M09a）

浮层把网页市集预览的开关、端口和 poe.ninja 汇率发给后端，后端据此在 `127.0.0.1` 上为浏览器扩展提供试算接口，见 [网页市集预览接口](web-preview.md)。

## `trade-preview`（M09b）

助手自带的市集窗口（EE2 `main/src/TradeWindow.ts`）每条结果发一次，参数 `{item_text, price, language: "en"|"zh_hans", realm: "pc-ggg"|"pc-tencent"}`，回复与扩展的 `POST /evaluate` 相同，见 [网页市集预览接口](web-preview.md#助手自带市集窗口m09b)。不经 HTTP，不受 `web-preview` 开关影响。

## `translate-item`（M02）

腾讯服 `Ctrl+D` 查价用：参数与 `evaluate-item` 相同（`item_text`、`game`），只做 P05 解析，不用引擎。`result`：`text`（英文游戏复制格式，稀有名保留客户端原文，EE2 用自己的英文解析器读）、`language`、`name`、`base_name`、`unique_name`、`names`（`[英文, 客户端原文]`，传奇名和基底名；国服市集按简中名搜索 `name`/`type`，词缀编号两服相同）、`unrecognized`。错误码 `bad-request`、`parse-failed`，失败时查价窗口显示 `message`。

后端错误码：`parse-failed`、`engine-unavailable`、`evaluate-failed`、`internal`，以及 `not-equippable`（通货、宝石等不能装备的物品，或 PoB 不认识它的基底）和 `no-slot`（当前 BD 没有能放这件装备的槽位）。后端启动后每 5 秒在后台预载 PoB 当前打开的 BD（含未保存的修改），首次评估不必等加载；在 PoB 里刚改完马上评估时，这次请求会先重载（约 0.2–1 秒）。
