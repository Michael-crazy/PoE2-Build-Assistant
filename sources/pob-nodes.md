# 固定树版本天赋节点离线索引

`sources/pob-nodes.en.json`（schema_version 1）从 `sources/pob.json` 固定的
本地 Git blobs 提取。复用 `index_pob_classes.py` 的版本清单、固定 SHA 校验、
文件哈希和数据表解析器，不联网、不执行 Lua，不接入攻略校验或 BD 生成。

```sh
python3 -B scripts/index_pob_nodes.py /tmp/poe2-pob-source /tmp/pob-nodes.en.json
cmp sources/pob-nodes.en.json /tmp/pob-nodes.en.json
python3 -B -m unittest discover -s scripts -p 'test_index_pob_nodes.py' -v
```

仅提取 `GameVersions.lua` 显式列出的版本，default/latest 保留固定引擎声明，
不代表线上赛季。每版独立保存 nodes，按数字 ID 排序，不跨版本合并。

| tree_version | 节点数 |
| --- | ---: |
| 0_1 | 3149 |
| 0_2 | 3404 |
| 0_3 | 4118 |
| 0_4 | 4701 |
| 0_5 | 4914 |

- `id` 来自节点 `skill`，依据固定源 `src/Classes/PassiveTree.lua:213`；
  `source_key` 为源 nodes 表键，不以表键替代 skill。
- `name_en` 原样保存，允许同名；`string_id` 为源 stringId，旧树缺失时为 null。
- `declaration` 保存节点表起始花括号所在相对文件、1 起始行号；版本也保留声明位置。
  `source` 保存仓库、分支、完整 SHA 与每个输入 blob 的 SHA-256。
- 复用受限显式键 Lua 数据表语法，只定位顶层 nodes，忽略 groups 内同名表。
  节点解析另支持源中实际使用的换行、引号、反斜杠转义；未知语法直接失败。
  不收录连线、属性、配置、可分配性或运行时动态生成节点。
- 同一版本重复 skill ID、重复表键、缺失/非整数/负数 ID、缺失名称直接失败；
  跨版本相同 ID 合法，身份和名称保持隔离。工作树修改和未跟踪版本不参与提取。

自编 Lua 与临时 Git 夹具验证 ID/表键区别、同名、版本隔离、重复 ID、声明行号、
嵌套误匹配、转义、旧树无 stringId、固定 blob 哈希及忽略本地修改。
来源许可沿用固定 fork 的 LICENSE.md 审查范围，未引入中文或外部数据。
攻略节点语义、生成、PoB 加载和客户端验收均待后续检查点。

离线 ID 查询接口为 `scripts/query_pob_nodes.py` 的
`NodeLookup(index, expected_source=None).query(tree_version, node_id)`。
必须指定索引内的版本键和非负整数 ID；不解析 `latest`、`default`，不按名称、
`string_id` 或 `source_key` 猜测身份，不跨版本查找。未知版本或非法 ID 抛出
`ValueError`。存在的 ID 返回 `single_candidate`，缺失 ID 返回 `not_found` 和空候选；
这些状态只说明固定源中是否有记录，不判断节点可分配性，也不代表已确认攻略字段。

```sh
python3 -B scripts/query_pob_nodes.py --tree-version 0_1 4
python3 -B -m unittest discover -s scripts -p 'test_query_pob_nodes.py' -v
```

返回结构沿用职业查询：`query` 保留版本、`by=id` 和原始数字值，`candidate_count`
与 `candidates` 对应；`source` 完整保留仓库、分支、SHA 和输入文件哈希，
`tree_version` 保留该版元数据及声明位置，候选保留全部节点字段及声明位置。
输入与返回值均以副本隔离。构造时拒绝同版重复 ID/表键及缺失身份或声明字段。
CLI 可用 `--index` 指定本地 JSON，但仍核对 `sources/pob.json` 的仓库/分支/SHA。
查询成功（包括 `not_found`）退出 0；未知版本、非法负数、索引读取/解析/校验失败
退出 1 并写 stderr；缺少版本或 ID、非整数 CLI 参数退出 2。

`test_query_pob_nodes.py` 使用自编两版本数据覆盖同名、共享/独有 ID、错位表键、
旧树空 string_id、未知版本、缺失 ID、非法输入、来源保留和副本隔离。
CLI 测试仅借用 manifest 元数据以测试来源核对，节点仍为自编数据，不作为上游实测。
本接口尚未接入攻略校验、MCP 或生成。
