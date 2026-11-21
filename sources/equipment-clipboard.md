# P05 离线中文装备剪贴板检查点

仅用 Python 标准库读取本地 UTF-8 文本，不访问系统剪贴板、网络或 PoB，不修改 BD。
`tests/fixtures/p05/` 的简繁文本、名称、数值、词缀和规则均完全自编。
繁体样本故意沿用简体测试词缀以复用同一规则，不代表真实简繁映射。
本检查点不是中文到英文的翻译器，也未确认基底/稀有度/词缀对应的生产 ID。

## 本地复用与来源审查

复用 M01/M02 保留完整 item 的适配器与 P02 原始文本试穿边界。
固定 PoB 提交 `601768bd105869618c3d6581b883e5d7aeec91b2`（见 `sources/pob.json`）；`LICENSE.md` 的 PoB Community 部分为 MIT。
`src/Classes/ItemsTab.lua:1484` 从 Paste 进入 CreateDisplayItemFromRaw；
`src/Classes/Item.lua:472` 的 ParseRaw 接受原始文本、读取英文 Item Class/Rarity、
名称和基底，且清理空白行。后续应复用这个引擎边界，在助手侧先保存未清理原文，
待 P03 有版本化授权映射后转换并调用 P02；没有复制或改动上游代码。

## 本轮契约

```sh
python3 -B scripts/equipment_clipboard.py tests/fixtures/p05/simplified.synthetic.txt --profile tests/fixtures/p05/profile.synthetic.json
python3 -B -m unittest discover -s scripts -p 'test_equipment_clipboard.py' -v
```

`inspect_clipboard(text, profile)` 输出完整 `raw_text`、有序 `sections` 和 `separators`。
每行保存 1 起算行号、含换行符的 raw 和不含换行符的 text；段索引从 0 起算。
只有独占一行的 `--------` 分段；空行、空段、空格、LF/CRLF、末尾无换行都保留。
原文是权威数据；未对属性、需求、注释、腐化状态作语义推断。

profile 只接受 `scope=authored_synthetic`。`mod_sections` 由作者明确指定待检查段，
不根据未知客户端布局猜测词缀段。`rules` 为唯一 synthetic.* ID 和全文匹配模板；
每个 `{number}` 对应 ASCII 有符号整数/小数。数字以原字符串捕获，不转换 float、
不改精度；零、前导零、正负号和区间的两个端点均保留。匹配 ID 仅用于测试。
非词缀段不参与匹配。选中段的非空行无规则匹配时输出 `unmatched_mod`（词缀未匹配），
多规则匹配输出 `ambiguous_mod`，两者都带原文、段和行号，且不生成已匹配记录。
未知词缀不使原文丢失，也不伪装成功；输出的 `pob_import` 始终为 `pending`。
空输入、错误 profile 或越界段索引报错，CLI 退出 1，无部分 JSON 输出；
CLI 退出 0 仅表示检查完成，调用方须读取 issues，不能据此进入试穿。

## 验证范围与后续

测试按行重建完整原文，核对段数、数字捕获、未匹配行位置、歧义、输入错误和 CLI。
没有真实游戏文本、Windows 剪贴板、基底识别、生产词缀 ID、英文装备生成或 PoB 导入验收。
后续独立检查点须取得 P03 授权且版本匹配的数据，以及双服真实脱敏文本（客户端版本、
赛季、采集方式），再确定段语义、映射和未识别提示，调用固定 PoB 引擎及 Windows 对照。
