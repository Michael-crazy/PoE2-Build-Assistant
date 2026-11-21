# P03 离线术语契约 v1

本检查点只提供 Python 3 标准库查找模块及原创虚构样例，不含真实游戏术语表、网站抓取、腾讯服译名或装备解析。未修改或运行 PoB。最终 P03 验收仍待真实数据、许可和双服样本核验。

在仓库根目录运行：

```sh
python3 -B scripts/terminology.py --catalog tests/fixtures/p03/terms.json --data-version synthetic/1 --alias '紙燈籠'
python3 -B scripts/terminology.py --catalog tests/fixtures/p03/terms.json --data-version synthetic/1 --id synthetic:skill:paper-comet
python3 -B scripts/terminology.py --catalog tests/fixtures/p03/terms.json --data-version synthetic/1 --alias '练习火花' --kind skill
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

不加 `--kind` 查询「练习火花」会返回两个候选，不自动选择。CLI 输出 UTF-8 JSON，退出码为 found=0、输入/版本/文件错误=1、not_found=2、ambiguous=3。从任意 cwd 可用脚本和目录的绝对路径运行。CLI 从 `sources/pob.json` 读取预期引擎 SHA，不根据目录内容猜版本。

## 数据与接口

- `schema=poe2-terminology/1` 是格式版本；`data_version=synthetic/1` 是本批数据版本；`engine_commit` 精确绑定 PoB SHA。加载时显式给出两项预期版本，不匹配则拒绝，不跨版本回退。实际游戏/赛季、树版本及服务区域须在真实批次接入时明确，不能把引擎 SHA 当作赛季名称。
- `entries` 中 `id` 全表唯一且区分大小写；`kind` 为 skill/passive/item/mod；`aliases` 必须含 en、zh-Hans、zh-Hant 的非空字符串列表；每个列表第一项约定为展示名，其余为别名。条目 `source` 引用该批 `sources` 的 origin/license/verification 记录。
- `Catalog.load(path, engine_commit=..., data_version=...)` 接受同格式本地 JSON。`by_id(id)` 返回 Term 或 None；`lookup(alias, kind=None)` 返回按 ID 排序的全部候选元组。Term 包含 ID、类别、全部原文别名及来源引用。
- 别名采用 Unicode NFC、casefold、去首尾及合并连续空白；不做自动简繁转换、模糊匹配、词缀数值提取或未知语言回退。简繁须显式录入。未知别名返回空集合，空白输入报错；同名允许跨类别或同类别出现，不覆盖。
- 示例 ID 使用 `synthetic:` 命名空间，是样例内部稳定键，与真实 PoB/game ID 无关。后续改译名应保持 ID；真实数据需独立命名空间及显式 PoB 键绑定，不能用翻译或列表序号生成 ID。不可声称跨引擎版本稳定，迁移需逐项核对。
- 本批只有一个原创来源；未来混合来源应拆分条目或扩展逐别名来源，记录每批采集版本、许可证据与校验摘要，不能将网站与腾讯样本统称为原创来源。字段存在只证明可追溯结构，不代表法律许可已核实。

## 固定源码复用依据（仅本地阅读）

已核对 `/tmp/poe2-pob-source` 的 HEAD 与 `sources/pob.json` 均为 `601768bd105869618c3d6581b883e5d7aeec91b2`，工作树干净。没有把其中的数据复制进本仓库。

- `src/Data/Skills/act_int.lua` 的 `skills[...]` 是技能效果键；`src/Modules/Data.lua:929–932` 赋给 `grantedEffect.id`。`src/Data/Gems.lua` 的 metadata 键、gameId、variantId、grantedEffectId 是不同层级，不能把宝石与效果名称直接混为同一 ID。
- `src/TreeData/0_5/tree.json` 的 nodes 包含节点键、skill 数值和 name。被动名称会重名，节点 ID 必须带树版本范围。`src/GameVersions.lua` 列出 0_1 至 0_5 树版本；liveTargetVersion 与 latestTreeVersion 也不是同一变量。
- `src/Data/Bases/axe.lua` 用英文名索引 `itemBases`，不可据此断言有跨版本稳定的物品 metadata ID；需补核基底与传奇物品分别如何绑定。
- `src/Data/ModItem.lua` 使用分阶词缀键，另有 affix、group 和数值模板，不能把 affix 名、stat ID、交易 API stat ID 当成同一键。本轮只实现术语查找，未实现真实词缀绑定。
- `LICENSE.md` 开头是 David Gowor 的 MIT 授权及保留声明要求；上述生成的数据文件另标明 Grinding Gear Games 数据版权。尚未完成对数据、译名、第三方素材各自授权范围的核实，不能由代码 MIT 直接推导全部数据可再分发。

## 下一批必须补的材料（本轮不获取）

1. 核对目标游戏/树/赛季版本；为技能、被动、基底/传奇、词缀逐类建立真实 ID 对照、重名及版本迁移用例，验证固定 PoB 中确实存在且语义相符。
2. PoE2DB 优先译名仍是计划来源，未访问或提取。先记录具体页面/数据版本、获取方式、作者/版权、再利用及再分发许可、署名要求和许可证据路径；无法确认时先取得许可，不导入或发布。其他上游项目的译名/数据也需分别检查，不能继承其代码许可假设。
3. 腾讯服仍缺玩家实际复制的技能、天赋、基底/传奇名称及完整装备词缀样本；记录客户端版本、赛季、服务区域、采样日期及可用于回归的授权，去除账号等个人信息。特别保留简体别名、多行词缀、数值范围、同名异物与无法识别行；不得把本批「试验纸灯」等虚构别名标成腾讯服实测。
4. 国际服英文/繁中对照同样缺真实样本。用户需参与的采样可并入 TASKS 的接入验证窗口；本轮不请求登录，不访问交易端点。
5. 数据和许可明确后再接入共享目录及 P04/P05/MCP；真实数据覆盖率、腾讯别名、版本对应关系及最终验收均未通过。本轮不发布或打包。
