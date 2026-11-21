# M06 离线价格到升级收益

此检查点只计算本地已完成试穿的性价比，不查询市场或汇率、不调用 PoB、不修改 BD。全部夹具数值均为自编，不是市场报价或真实引擎证据。

```sh
python3 -B scripts/upgrade_value.py tests/fixtures/m06/candidates.synthetic.json
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

复用 M01/M02 的归一化挂单字段 `id/realm/league/price` 和 P02 的 `baseline/replacement` 指标。函数 `calculate_upgrade(listing, trial, *, realm, league, currency, metric, rates=None)` 接收一个候选。调用方负责将同一候选、BD、装备槽、配置和引擎版本的已完成试穿与挂单关联；本模块不能从指标推断装备身份。CLI 的 JSON 中 `context` 提供上述关键字上下文，`candidates` 每行包含 `listing`、`trial`，`rates` 为可省略的整批手动汇率表。输入输出均保留原报价和完整试穿对象，不修改输入。

- 服区必须明确为 `international` 或 `tencent`，赛季为调用方明确指定的名称；挂单上下文不符时报错，不混合两服或赛季。
- `metric` 可选 `CombinedDPS`、`Life`、`EnergyShield`、`Armour`、`Evasion`，后四项为独立生存指标，不合成为无定义的生存总分。
- 提升 = replacement[metric] − baseline[metric]，性价比 = 提升 / 统一通货价格。单位是指标绝对量/通货，非百分比；允许负值和零提升，零基准不触发除零。
- 汇率表 `{realm, league, currency, units}` 的 `currency` 是目标通货，`units` 的每个值表示一单位来源通货值多少目标通货。例如 `currency: exalted, units: {divine: 100}` 表示 1 divine = 100 exalted；报价 2 divine 换算为 200 exalted。不反推汇率或经第三种通货转换。
- 同通货价格直接使用，`rate_used=1`，不要求汇率表。跨通货仅使用同服同赛季且目标通货一致的明确正有限汇率。
- `status=ok` 时返回 `normalized_price`、`rate_used`、`gain_per_currency`。缺报价 `missing_price`、缺来源通货汇率 `missing_rate`、汇率服区/赛季不符 `rate_context_mismatch`、目标通货不符 `rate_currency_mismatch` 时这三项均为 null，仍返回完整试穿与五项 delta。
- 无效价格（零、负、布尔、非数、非有限值）、被使用的无效汇率和无效试穿指标报错；不会将其伪装成免费候选。CLI 整批计算完成才输出，失败返回非零及错误文本。

合成示例：DPS 1000 → 1200、2 divine 得 1 DPS/exalted；1000 → 1100、50 exalted 得 2 DPS/exalted；未标价候选保留 DPS +300，但性价比 null。Life 100 → 90、50 exalted 得 −0.2 Life/exalted。此处只交付数值和可用状态，候选筛选、排序与 UI 属后续 M05/M08/M09。

实时汇率来源仍待办：尚未选择或验证任何提供方、时效规则、来源证据与失败刷新行为。后续接入必须保留服区、赛季、通货方向及来源/时间，按正式数据验证后再接受实时结果；本轮手动合成汇率不证明真实两服汇率能力。
