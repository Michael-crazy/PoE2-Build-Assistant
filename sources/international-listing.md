# M01 离线挂单适配器检查点

本检查点只读取本地 JSON，不包含 HTTP 客户端、查询构造、登录、网页链接生成或通货换算。样本完全自编，不代表真实物品平衡、赛季、市场报价或官方接口承诺。

## 复用评审

- 依据固定 PoB 提交 `601768bd105869618c3d6581b883e5d7aeec91b2`（见 `sources/pob.json`）。
- `src/Classes/TradeQueryRequests.lua` 的 `FetchResultBlock`（约 286–459 行）读取 `response.result`、`trade_entry.item`、`item.rarity`、物品属性/词缀，以及 `listing.price.amount/currency/type`、挂单 ID。本适配器沿用该数据边界，保留完整 item 供后续导入，避免重写 PoB 的物品文本转换。
- 该上游还已有查询生成、请求队列和限流组件，依赖 PoB Lua UI、下载器及认证状态。本次不复制其网络代码、不改 PoB；后续接网应优先在原组件上集成，并先核对授权和正式使用约束。
- 该检出的 `LICENSE.md`：PoB Community 部分为 MIT 授权。本适配器为独立 Python 实现，未复制上游代码。
- 物品解析与游戏内查价由改造后的 Exiled Exchange 2 负责（见 [assistant-shell.md](assistant-shell.md)）；中文解析见 P05。

## 离线契约和复现

```sh
python3 -B scripts/trade_listing.py tests/fixtures/m01/listings.json --league 'Offline Test League'
python3 -B -m unittest discover -s scripts -p 'test_trade_listing.py' -v
```

输入为含 `result` 数组的 JSON。每行需要非空 `id`、`item.league/typeLine/rarity` 和 `listing` 对象；指定赛季必须与每行一致。输出按原顺序包含 `id/realm/league/item/price`，realm 固定 `international`。完整 item 深复制；本轮不解析或匹配词缀 ID。

价格保留 amount、currency 和 type，不比较跨通货价格。缺失或 null 价格输出 null；非正数、布尔值、非有限数和不完整价格报错。空结果是正常空列表。响应错误、损坏结构、跨赛季或重复 ID 导致整批失败，CLI 返回 1 且不输出部分结果。

`tests/fixtures/m01/listings.json` 为手写的传奇、四词缀稀有样本：虚构名称、ID、赛季和报价；无账号、私聊、token 或真实用户数据。对照测试验证装备/报价不变及无输入修改。此夹具只验证本地契约，不能据此确认实际响应字段兼容性。

## 待实网验收

后续经授权接入后，固定真实赛季，分别查询一件传奇及多词缀稀有装备。记录同一挂单 ID、筛选条件、装备全部词缀、报价数量/通货/类型，与官方市集逐项对照；再核对登录、限流、失效挂单和 Windows 展示。当前均未执行，M01 未验收；本检查点不接续其他任务。
