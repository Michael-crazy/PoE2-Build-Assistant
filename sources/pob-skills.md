# 固定版本技能英文索引

`sources/pob-skills.en.json` 是 P03 名称映射的离线起点，schema_version 为 1。
源为 `pob.json` 的 fork、分支和完整提交；只从本机 Git 对象读取该提交的
`src/Data/Skills/*.lua`，不联网，不执行 Lua，不生成 BD，也不更改 MCP 输入结果。

复现（已有本地固定 fork，无需下载或安装）：

```sh
python3 -B scripts/index_pob_skills.py /tmp/poe2-pob-source /tmp/pob-skills.en.json
cmp sources/pob-skills.en.json /tmp/pob-skills.en.json
python3 -B -m unittest discover -s scripts -p 'test_index_pob_skills.py' -v
```

要求本地 HEAD 与固定提交一致。工作树修改及未跟踪文件不参与提取。
输出按 ID 排序，不含本机路径、生成时间等不可复现字段；每个源文件记录 SHA-256
和声明数量。`SkillAssets.lua` 为图片坐标表，记录哈希、0 条技能，不复制图片。

每条 `skills` 包含 `id`、`name_en` 和 `declarations`（相对源文件、1 起始行号）。
当前共 1432 条声明、1429 个 ID；同一 ID 同名重复声明合并，保留全部声明位置。
同一 ID 异名直接失败。8 个空名保留空字符串，不猜译、不拿 ID 冒充名称。
103 个非空英文名称对应多个 ID，禁止按名称直接覆盖；主动、辅助、怪物、召唤物、
触发技能都在索引范围，名称存在不表示可作为主技能或可直接选用的宝石。

提取器只接受固定版本已核对的生成格式：行首 `skills["ID"] = {`，下一行
`name = "英文名",`。不解析嵌套 name。遇到新声明格式或转义字符串失败，
须先核对新版本格式，不静默遗漏。中文译名、服区别名及宝石 ID 关系仍待 P03。

来源与许可：固定 fork Git 提交 `601768bd105869618c3d6581b883e5d7aeec91b2`。
源数据文件标注 `Skill data (c) Grinding Gear Games`；PoB 项目 `LICENSE.md`
包含 David Gowor 的 MIT 许可及其他组件声明。英文技能数据的版权标注不能当作
编年史中文译名的授权，本检查点不引入任何中文外部数据、不作发布验收。

## 离线候选查询

```sh
python3 -B scripts/query_pob_skills.py --by name 'Fireball'
python3 -B scripts/query_pob_skills.py --by id 'FireballPlayer'
python3 -B -m unittest discover -s scripts -p 'test_query_pob_skills.py' -v
```

默认只读仓库索引，`--index <本地文件>` 可指定另一份索引；CLI 要求其 schema 为 1，
仓库、分支、提交与 `sources/pob.json` 完全一致，避免混用引擎版本。
可复用的 `SkillLookup(index, expected_source)` 接口接受已读入的版本化索引；
省略 expected_source 时仍要求有效版本信息，结果携带实际版本，不声称匹配当前引擎。

`--by name` 只按完整英文名匹配，`--by id` 只按 ID 匹配；区分大小写，
不去除查询两端空格、不模糊匹配、不翻译、不跨名称/ID 命名空间回退。
结果记录原查询、来源仓库/分支/提交、候选数和按 ID 排序的完整候选（含声明位置）。
`status` 有四种：`single_candidate`（一条）、`ambiguous`（多条）、
`not_found`（零条）、`empty_query`（空串或全空白，零条）。这些均为正常查询，退出码为 0；
文件读取、JSON、schema、来源不匹配及索引记录错误返回非零退出码，错误写 stderr。
空名不会参与名称查询，按 ID 查到时仍保留 `name_en: ""`。即使只有一条候选，
也不自动选技能、不回填攻略字段、不判断主技能资格、不生成 BD；现有 MCP 返回不变。

`tests/fixtures/a01/skill-query-index.json` 是独立自编数据，使用虚构仓库和提交，
覆盖同名多 ID、空名、名称与其他 ID 重合；它不冒充上游数据，CLI 的固定源检查会拒绝它。
