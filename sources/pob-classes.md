# 固定版本职业、升华与树版本离线索引

`sources/pob-classes.en.json`（schema_version 1）从 `sources/pob.json` 固定的本地
Git 对象提取，不联网、不执行 Lua、不生成 BD。职业／升华候选已接入攻略校验与 MCP 返回。
要求本地 HEAD 与 manifest 完整 SHA 一致；工作树修改及未跟踪文件不参与提取。

```sh
python3 -B scripts/index_pob_classes.py /tmp/poe2-pob-source /tmp/pob-classes.en.json
cmp sources/pob-classes.en.json /tmp/pob-classes.en.json
python3 -B -m unittest discover -s scripts -p 'test_index_pob_classes.py' -v
```

`source` 保留 repository、branch、commit，以及每个输入文件的 SHA-256。
`src/GameVersions.lua` 的 `treeVersionList` 定义顺序与支持范围，`treeVersions`
提供 display、num 及声明位置。default/latest 分别按该源的首项/末项表达式提取；
它们是该固定引擎的声明，不表示当前线上赛季。只读取列表中的树，不扫描目录猜版本。
每个版本从 `src/TreeData/<版本>/tree.lua` 顶层 classes 表提取职业及其升华；
每个版本、职业和升华记录相对源文件与 1 起始声明行号。

| tree_version | 职业数 | 升华数 |
| --- | ---: | ---: |
| 0_1 | 6 | 12 |
| 0_2 | 7 | 17 |
| 0_3 | 7 | 18 |
| 0_4 | 8 | 21 |
| 0_5 | 8 | 23 |

职业的 `source_index` 是原始表序号，`integer_id` 是源 integerId；二者不能互换。
固定源 `src/Classes/PassiveTree.lua:102` 起以 integerId 重建职业表；升华继续使用
原 ascendancies 表序号。索引保留 `ascendancy_index`、字符串 `id`、`internal_id`
和 `name_en`，不从名字或 internalId 的数字后缀推导编号。运行时补入的 0/None
不属于源职业声明，未伪造为索引记录。名称不跨版本合并，也不假定唯一。

提取器仅接受已核对的版本声明及数据表语法（显式键、嵌套表、字符串、数字、布尔值），
仅解析 classes 子树，不收录天赋节点、图片、技能组或配置。重复键、版本清单不一致、
不支持的字符串转义和缺失身份字段直接失败，避免静默漏项；源格式变化须先核对。
`test_index_pob_classes.py` 使用自编 Lua 字符串和临时 Git 仓库，覆盖同名升华、
不同命名空间编号、嵌套 name/花括号、跨版本职业 ID 变化、声明行号、错误格式、
固定 SHA、忽略未提交内容及复现一致性，不冒充真实攻略或客户端验收。

来源为 fork 提交 `601768bd105869618c3d6581b883e5d7aeec91b2`，许可沿用
固定源 `LICENSE.md` 的审查范围；本轮不引入中文译名及外部授权，不作发布验收。
离线查询接口为 `scripts/query_pob_classes.py` 的 `ClassLookup(index, expected_source=None)`：
`query(tree_version, kind, by, value, class_integer_id=None)`。调用者必须传入索引中的
明确版本键，不把 `latest`、`default`、空值或未知版本解析为其他版本；未知版本抛出
`ValueError`，CLI 返回 1 并在 stderr 说明，缺少必填参数返回 2。

```sh
python3 -B scripts/query_pob_classes.py --tree-version 0_5 --kind class --by integer_id 2
python3 -B scripts/query_pob_classes.py --tree-version 0_5 --kind ascendancy --by name Deadeye --class-integer-id 2
python3 -B -m unittest discover -s scripts -p 'test_query_pob_classes.py' -v
```

- `kind=class` 支持 `by=name|integer_id|source_index`。
- `kind=ascendancy` 支持 `by=name|id|internal_id|ascendancy_index`。
- 名称和字符串 ID 精确匹配，不去空白、不改大小写、不翻译、不从数字后缀猜编号。
  Python 接口的编号值必须为非负整数，CLI 按编号类型转换；不会把文本名当编号。
- 升华可用 `class_integer_id` 限定所属职业；只接受职业 integer ID，不使用 source_index。
  未指定归属时返回版本内所有候选，每个候选都有 `class_identity`，升华另带 `ascendancy`。
  升华表序号仅在所属职业内唯一，同一序号可返回多个职业的候选。
- 返回 `empty_query`、`not_found`、`single_candidate` 或 `ambiguous`，不自动选择。
  归属不符、未知名称或编号返回 `not_found`；未知版本属于调用错误。
  返回原始查询、候选数、源及树版本声明和身份声明位置，副本修改不会污染后续查询。
- CLI 强制核对固定 manifest 的仓库/分支/SHA；类接口允许注入自编索引。
  `test_query_pob_classes.py` 自编两版本、同名职业/升华、交叉名称/ID 和错位编号，
  验证命名空间、职业归属、版本隔离、错误和可变对象隔离；CLI 自编数据仅借用
  manifest 元数据测试固定来源检查，不冒充上游或客户端样本。

攻略校验与 MCP 现通过 `class_ascendancy_candidates` 返回本接口候选，见
[输入契约](guide-input-contract.md#离线职业升华候选返回)。不生成 BD；候选存在不等于攻略字段已确认。
中文映射、技能组、装备槽位及配置语义和实际引擎加载仍待验证。
