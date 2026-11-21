# data/ 目录的数据许可

本仓库代码按 MIT 许可（见根目录 `LICENSE`），**但 `data/` 下的游戏术语数据不适用 MIT**，按以下来源各自的条款使用。

## 流放编年史（PoE2DB）派生数据：CC BY-NC-SA 3.0

以下文件由 [流放编年史 PoE2DB](https://poe2db.tw/cn/)（poe2db.tw，简中 `/cn/`、繁中 `/tw/`、英文 `/us/` 页面）整理生成：

- `data/terms/poe2db-1.0/`：装备类别、基底、传奇、词缀、宝石、通货、天赋等的简中/繁中/英文对照表（每个文件的 `metadata.sources` 记有来源页面和抓取时间）；
- `data/terms/pob-localization/`：由上述表与 Path of Building 数据对应生成的 PoB 显示表；
- `data/terms/pob-ui/` 中取自 PoE2DB 的游戏术语。

PoE2DB 站点页脚写明：“Wikis Content is available under CC BY-NC-SA 3.0 unless otherwise noted”（见 [General disclaimer](https://poe2db.tw/General_disclaimer)，2026-11-21 核对）。因此这些派生数据按 [知识共享 署名-非商业性使用-相同方式共享 3.0（CC BY-NC-SA 3.0）](https://creativecommons.org/licenses/by-nc-sa/3.0/deed.zh) 发布：

- **署名**：数据来自 流放编年史 PoE2DB（https://poe2db.tw），由 PoE2-Build-Assistant 贡献者整理为 JSON。再分发时请保留本说明。
- **非商业性使用**：不得将这些数据用于商业目的。
- **相同方式共享**：改编后的数据须以相同许可发布。

PoE2DB 的部分条目沿用 PoE Wiki 内容，同样按 CC BY-NC-SA 3.0 使用。游戏名称、物品、技能等的著作权和商标属于 Grinding Gear Games（国服内容由腾讯运营）。

## PoB 界面译文：`data/terms/pob-ui/`

PoB 独有的界面文字（不在编年史里的按钮、提示、计算页说明等）的译法取自：

- [PoeCharm](https://github.com/Chuanhsing/PoeCharm) / [PoeCharm2](https://github.com/Chuanhsing/PoeCharm2)（Chuanhsing）的简体中文翻译表；
- [PathOfBuilding-PoE2-i18n](https://github.com/woolkingx/PathOfBuilding-PoE2-i18n)（woolkingx）的 zh_CN / zh_TW 译文。

这两个项目的仓库在 2026-11-21 核对时都**没有为译文写明单独的许可**（PoeCharm 仓库无 LICENSE 文件；PoB2-i18n 的 LICENSE.md 只有 PoB 原有的 MIT 及第三方库许可）。我们注明出处并感谢原译者；如果译者对使用方式有异议，请开 Issue，我们会替换相关条目。`overrides.json` 中经人工审核的词条注明了各自来源。

## 市集数据：`data/trade/`

`stats.json`、`currency.json`、`leagues.json` 由官方市集公开的数据接口（国际服 `www.pathofexile.com/api/trade2/data/*`、国服 `poe.game.qq.com/api/trade2/data/*`，无需登录）合并生成，只含词缀条件、通货名称与赛季名，版权属于 Grinding Gear Games 与腾讯。
