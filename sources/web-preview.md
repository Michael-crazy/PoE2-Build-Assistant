# 网页市集预览接口（M09a）

浏览器扩展（[Michael-crazy/poe-trade2text](https://github.com/Michael-crazy/poe-trade2text)，fork 自 `intGus/poe-trade2text`，MIT）在国际服 `www.pathofexile.com/trade2` 每条结果旁显示本机助手的试算。扩展把结果转成物品文本（上游 `parseItemData`），经后台脚本发到助手后端；后端用和游戏内浮层同一条评估流程（`Backend.evaluate_item`：U02 当前 BD、M06 指标），性价比与 M08b 相同。

## 开关、端口和汇率：浮层 → 后端

助手设置（EE2 配置 40 版，`assistant-eval` 小部件）：

| 键 | 默认 | 说明 |
|---|---|---|
| `webPreview` | `true` | 是否监听扩展的请求 |
| `webPreviewPort` | `37428` | 监听 `127.0.0.1` 的端口，1024–65535 |

PoB 选项“游戏内助手”有对应两行（“网页市集预览”“网页预览端口”），旧配置升级时补默认值并按 B04 写回。

浮层启动 3 秒后、设置或 poe.ninja 汇率变化时、之后每 2 分钟，经 stdio 发：

```json
{"protocol": "assistant-shell/1", "id": 12, "method": "web-preview",
 "params": {"enabled": true, "port": 37428, "value_currency": "divine", "rates_source": "poe.ninja",
            "currencies": {"exalted": {"name": "崇高石", "en": "Exalted Orb", "divines": 0.0021}, "...": {}}}}
```

- `currencies`：市集通货表（`trade-currency.ts`）的简中名、英文名和 poe.ninja 价（以神圣石计，取不到就没有 `divines`）。`rates_source` 为 `null` 表示 poe.ninja 还在加载。
- 结果 `{"listening": true, "port": 37428, "error": null}`；端口被占用时 `listening` 为假、`error` 为中文原因（后端日志同样一行）。`enabled: false` 关闭监听。定时重发让后端重启后自动恢复监听。

## 扩展 → 后端：`POST http://127.0.0.1:<port>/evaluate`

请求（`Content-Type: application/json`，不超过 64 KB）：

```json
{"item_text": "Item Class: Gloves\nRarity: Rare\n...", "language": "en",
 "price": {"amount": 50, "currency": "exalted", "currency_text": "Exalted Orb"}}
```

`price` 可省略；`currency` 是价格图标上的市集代号，没有时按 `currency_text`（英文名）在通货表里找。

响应（HTTP 200）：

```json
{"ok": true, "item": {"name": "...", "base_name": "...", "unique_name": null, "unrecognized": []},
 "build": {"name": "...", "source": "live", "unsaved": false},
 "slot": {"slot": "Gloves", "label": "手套", "summary": "比当前手套强：...", "dps_percent": 10.0, "dps_absolute": 100, "ehp": 300},
 "slots": [...], "price": {...},
 "value": {"base": "divine", "base_name": "神圣石", "price_name": "崇高石", "price_in_base": 0.1, "dps_percent": 100, "ehp": 3000}}
```

- `slot` 是浮层的默认槽位（`default_slot`），`slots` 列出全部可放槽位。
- `value`：没有价格时为 `null`；换算不了时只有 `message`（`正在获取 poe.ninja 汇率…`、`poe.ninja 没有X的价格`、`不认识的通货：X`）。
- 评估失败：`{"ok": false, "code": "...", "message": "中文原因"}`，代码同浮层（`not-equippable`、`no-slot`、`parse-failed`、`engine-unavailable`……）；只支持英文页面（`unsupported-language`）。

## 助手自带市集窗口（M09b）

- EE2 在自己的窗口里打开当前服的 trade2（国际服 `www.pathofexile.com`，持久分区 `persist:trade-ggg`；国服 `poe.game.qq.com`，与查价登录同一会话），把扩展的 `content.js`、`assistant/preview.js`、`preview.css` 原样（EE2 `main/trade-preview/`，哈希在测试里核对）注入一个隔离世界；preload 只向这个隔离世界暴露 `poe2AssistantTransport.evaluate`，网站自己的脚本拿不到。
- 请求经 Electron IPC 到主进程（只认本窗口、页面在本站 `/trade2` 下的请求，一次一条），再经 stdio 方法 `trade-preview` 到后端；不走 `127.0.0.1`，扩展端口关闭时也能用。
- 语言按站点：国服页面是“上游导出的英文段名 + 简中名称和词缀”，以 `zh_hans`（P05，`game.language = cmn-Hans`）解析。
- 汇率按服：浮层每次推送 `web-preview` 时带 `currencies`（poe.ninja）和 `tencent_currencies`（M08b 手填的腾讯服汇率），开关关闭时也推；国服价格的通货名是简中，按 `name` 匹配。国服缺汇率时提示到 PoB 选项或助手设置里填写。

## 安全

- 只监听 `127.0.0.1`。任何网页都能向 localhost 发请求，所以每个请求先查 `Origin`：只接受 `chrome-extension://dbhocbceaidfohejkkcllnbbcaeaikkm`（扩展 `manifest.json` 的 `key` 固定了这个 ID）和 `moz-extension://<UUID>`（Firefox 每次安装随机，无法固定）；没有 `Origin`、`null` 或网页来源一律 403。`Host` 只认 `127.0.0.1:<port>`、`localhost:<port>`（防 DNS 重绑定）。
- 不发任何 CORS 头：扩展后台脚本有 `http://127.0.0.1/*` 主机权限，不需要；网页即使发出请求也读不到响应。
- 只有 `/evaluate` 一个路径、只收 POST；只试算，不改 BD、不写文件。
- 扩展的内容脚本不直接请求（它的 Origin 是市集网页），统一交给后台脚本，后台脚本只接受本扩展自己的消息。

## 实现位置

- 后端：`scripts/web_preview.py`（`WebPreview`），`assistant_backend.py` 的 `web-preview` 方法；测试 `scripts/test_web_preview.py`。
- 浮层：EE2 `renderer/src/web/assistant/web-preview.ts`、`WidgetAssistantEval.vue`（`syncWebPreview`）。
- 扩展：`assistant/background.js`、`assistant/preview.js`、`assistant/preview.css`、`assistant/options.*`，`manifest.json` 加了后台脚本、存储权限、`127.0.0.1` 主机权限和 `key`；上游文件只改了 `manifest.json`。
