# 国服市集接入调研（2026-11-17）

只读调研，没有发出真实查询。标注“推断”的项由 M10 抓包确认。

## 入口

- 国服 PoE2 网页市集：`https://poe.game.qq.com/trade2`（PoE1 为 `/trade`）。来源：poe2lens-trade 支持站点表、poe2-trade-assistant 的 manifest。
- 国服 PoE1 API 与国际服结构一致：`/api/trade/search/{league}`、`/api/trade/fetch/...`、`/api/trade/exchange/...`、`/api/trade/data/stats|items|static`（见 awakened-poe-trade-cn 源码）。
- 国服 PoE2 API 推断为 `/api/trade2/...`，目前没有开源项目实际调用过。
- 鉴权：国服分支要求用户粘贴登录后浏览器的整段 Cookie，代理补 `Origin: https://poe.game.qq.com`、`X-Requested-With: XMLHttpRequest`。国际服 trade2 可以匿名查询。
- 限流：国际服按 `x-rate-limit-rules`、`x-rate-limit-{rule}`、`x-rate-limit-{rule}-state` 动态限速（EE2 `renderer/src/web/price-check/trade/common.ts`）。国服推断相同，未验证。

## 可复用项目

| 项目 | 许可 | 可借鉴 |
|---|---|---|
| [Kvan7/Exiled-Exchange-2](https://github.com/Kvan7/Exiled-Exchange-2) | MIT | 外壳、浮层、物品解析、trade2 查询；只有 `pc-ggg`/`pc-garena`，没有简中数据 |
| [SuinegXY/awakened-poe-trade-cn](https://github.com/SuinegXY/awakened-poe-trade-cn) | MIT | `pc-tencent` realm、Cookie 代理（`main/src/proxy.ts`），仅 PoE1 |
| [yl-tianxian/Awakened-PoE-Trade-Simplified-Chinese](https://github.com/yl-tianxian/Awakened-PoE-Trade-Simplified-Chinese) | MIT | 简中 APT，代理指向 poe.game.qq.com，仅 PoE1 |
| [Hsiung-Shao/Exiled-Exchange-2-zh-TW](https://github.com/Hsiung-Shao/Exiled-Exchange-2-zh-TW) | — | EE2 繁中补丁 |
| [AilveGei/poe2-trade-assistant](https://github.com/AilveGei/poe2-trade-assistant) | 无 | 国服 trade2 网页扩展结构（MV3），可供 M09 参考 |
| [orcwind/poe2lens-trade](https://github.com/orcwind/poe2lens-trade) | 无 | 双服 trade/trade2 网页扩展 |
| [bigdogaaa/PoE2PriceTracker](https://github.com/bigdogaaa/PoE2PriceTracker) | GPL-3.0 | 国服通货价格，数据来自 poe2db.tw/cn/Economy，不调用市集 API |

没有找到“简中剪贴板 → 国服 trade2 查询”的现成 PoE2 工具。方案：在 EE2 fork 中按 APT 国服分支的做法加入 `pc-tencent` 和 Cookie 代理，并补简中数据。

## M10 待确认

国服 trade2 的 API 路径、必需 Cookie 字段与有效期、限流头和数值、中文赛季名、data/stats 是否返回简中词缀。
