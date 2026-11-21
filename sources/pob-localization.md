# PoB 游戏术语显示层（P03 设计）

数据由 `scripts/pob_localization.py` 从 `data/terms/poe2db-1.0`（D01）和固定 PoB `601768b` 生成，输出在 `data/terms/pob-localization/`：

| 文件 | 键 | 内容 |
| --- | --- | --- |
| `gems.json` | `gems`：Gems.lua 键（存档 `gemId`）；`skills`：`grantedEffectId` | en、zh_hans、zh_hant |
| `mods.json` | `mods`：Mod*.lua 的词缀 ID；`lines`：模板键 | 每行 `key` + 中文模板，词缀名 `affix` |
| `bases.json` / `uniques.json` | 英文名 | 中文名；传奇另有逐行模板 `lines` |
| `coverage.json` / `coverage.txt` | — | 各类 PoB 总数、命中、缺失、歧义、仅 PoE2DB 有 |

模板键是 `poe2db_terms.number_key`：数字和范围换成 `#`，去掉正负号和多余空白，小写。只有 PoE2DB 英文模板和 PoB 英文行的键相同、中文 `#` 个数一致的条目才入表；同一键有多种译法算歧义，不入表。未入表的条目保持英文。

## 显示层查表

- 只在绘制文字时替换。`gemId`、`skillId`、词缀 ID、物品原文、存档 XML、计算用的 modList 都保持英文原值，切换语言不重算、不改存档。
- 语言来自 P04 启动器的 `POE2_ASSISTANT_LOCALE`（`zh-CN` 用 zh_hans，`zh-TW` 用 zh_hant，`en` 或未设时不加载表）。PoB 端是 `src/Modules/AssistantTerms.lua`：表随分支放在 `poe2-assistant/terms/`（本目录的 gems/mods/bases/uniques/passives，`source.json` 记生成提交和 SHA-256），第一次用到时用自带 `dkjson` 读（全部约 0.2 秒），缓存在全局 `assistantTerms`。
- 宝石与技能：显示 `gemData.name` / `grantedEffect.name` 处先按 `gemId`，再按 `grantedEffectId` 查；只有英文名的地方（技能组标签是逗号连接的宝石名、`nameSpec`）按英文名查，同名多译的不用。查不到显示英文。
- 词缀：PoB 物品行不带词缀 ID，一律按 `number_key(行)` 查：传奇先查 `uniques[name].lines`，再查 `mods.lines`，再查 `mods.mods` 里所有同键模板（全部同译才用）。行首颜色码保留；行尾 `^8(Not supported in PoB yet)` 这类附注原样保留，只换前面的正文。用 `localize_line` 的规则把英文行里的数值依次填进中文 `#`：模板自带正负号时保留，但英文值带相反符号时换成英文的符号；模板无符号时负值保留负号；范围 `(a-b)` 原样填。数值个数对不上就显示英文。
- 基底和传奇名：物品标题、物品列表和槽位下拉按英文名查；魔法物品（有前后缀）和稀有物品随机名保持英文。物品原文不变。物品库、天赋树和宝石下拉另外接受简中包含匹配（完整的多语言搜索归 P09）。
- 定制集中在 `AssistantTerms.lua`，上游文件只在调用点改一两行（作为 `poe2-assistant` 分支上的提交，见 [pob-branch.md](pob-branch.md)）。
- 核对：`ops/check_pob_terms.py --pob <树> [--build BD.xml ...]` 在 HeadlessWrapper 里逐行比较中英数值（英文数词写成数字算一致），`ops/rebase_check.py` 每次都跑整树和传奇库这一项；`scripts/test_pob_terms_display.py` 核对 Lua 与 Python 的键和填值规则一致。

## 已知限制

- PoE2DB 是 1.0，PoB 是 0.23.1：PoB 有而 1.0 页面没有的条目（旧词缀、改名宝石、升华技能）保持英文；1.0 新增条目只计入 `poe2db_only`。
- `ModItemExclusive`（传奇专属词缀）在 PoE2DB 页上没有 ID，改由 `uniques.lines` 按文本覆盖。`ModRunes` 以符文名为键，格式不同，本轮未接（D01 有 `socketables` 可后续接）。
- 中文语序与英文数值顺序不同的模板（个别“附加 # 至 #”）按出现顺序填值，需在 Windows 实测时抽查。

## 天赋树（`passives.json`）

- 来源：编年史天赋树页 `https://poe2db.tw/cn/passive-skill-tree/` 由 `passive-skill-tree.<hash>.js` 加载 `/data/passive-skill-tree/4.5/data_{us,cn,tw}.json?8`（整棵树一个文件，含 `nodes`（键为节点 skill ID，含 name、stats、isNotable/isKeystone/isJewelSocket/isMastery/ascendancyName）和 `classes[].ascendancies[]`）。三语共 3 个请求，缓存在 Linux `~/.local/state/poe2-assistant/poe2db-cache/tree/`，URL 记在 `manifest.json`。
- 生成：`pob_localization.py --tree <缓存目录>`；PoB 端读 `GameVersions.lua` 的 latestTreeVersion（0_5）对应的 `TreeData/0_5/tree.lua`（PassiveTree.lua 实际加载的文件），用 `index_pob_classes.table_at` 解析。
- 键：`nodes[skill ID]`，即存档里的节点号。`kind` 为 ascendancy / keystone / notable / jewel_socket / small / mastery / class_start。
- 名称：编年史英文名与 PoB 相同才给 `zh_hans`/`zh_hant`；改名的保持英文。
- 属性行：`lines` 与 PoB 节点 `stats` 逐行对齐，`null` 表示该行显示英文。在同一节点内按 `number_key` 找编年史英文行，中文行里的数字换成 `#`；中文数字必须正好是英文行的数字。中文调换了数字顺序时带 `order`（每个 `#` 取英文第几个数值），由 `localize_line(line, template, order)` 填值。编年史标记 `[Ref|文字]` 只取显示文字。
- 一条属性被 PoB 折成多行（后续行小写开头）时，整组都配上才用，否则整组显示英文，避免半句中文半句英文。
- 升华名：`ascendancies[英文名]`，按 `internalId` 与编年史 `classes[].ascendancies[].id` 对齐，英文名相同才入表。
- 可切换节点：PoB 节点的 `options`（属性点三选一键为 1..3；职业/升华变体键为职业或升华名，如 Druid、Abyssal Lich）。备选的 ID 不是编年史节点 ID，编年史也没有 options 字段，所以按英文对：名称取编年史所有同英文名节点的中文，全部一致才用；属性行按 `number_key` 在整棵编年史树里找同模板行，中文模板唯一才用。输出 `node_options.hosts[宿主节点号][选项键] = 备选 ID` 和 `node_options.options[备选 ID]`（`en`、`zh_hans`/`zh_hant`、`lines`，格式同 `nodes`）。只有边框的选项（Abyssal Lich 的部分节点）不入表，显示宿主自身文字。

### 显示层
天赋悬浮提示和搜索按节点当前状态查：`passives.nodes[id]` 的英文名等于节点当前 `dn` 时用它；否则在 `node_options.hosts[id]` 的备选里找英文名相同的（职业/升华变体、属性三选一替换后 `dn` 变了，id 仍是宿主号）；升华起点用 `ascendancies`。属性行按 `number_key` 在该条目的 `lines` 里找模板（珠宝合并后的行、数值被放大后的行也能对上），找不到时用全树同键且译法唯一的模板，但 PoB 折行的行（本行或下一行小写开头）只用节点自己的表。节点计算、分配、存档不变。

## 宝石提示正文（D02，`gem_tooltips.json`）

`scripts/pob_gem_tooltips.py` 生成（`ops/poe2db_update.py` 的 `gem_tooltips` 步骤）。数据来源有两部分：一是固定 PoB 引擎里 `pob_gem_lines.lua` 导出的英文行，二是编年史宝石页 `/us|cn/<宝石>`（经 `scripts/poe2db_fetch.py` 读缓存）。格式为 `poe2-gem-tooltips/1`，只有 `zh_hans`。

| 键 | 内容 |
| --- | --- |
| `effects[grantedEffectId]` | `gem`（PoB gemId）、`page`（编年史页名）；`lines`、`quality`：`number_key` → `{"zh_hans": 模板[, "order": [...]]}`；`description`：`{"en", "zh_hans"}`，只在宝石的第一个效果上 |
| `tags` | 标签英文 → 中文（页面标签行与类型行，如 `Fire`→`火焰`、`Support`→`辅助`；D02-ui 起再加 D01 宝石类别表 `skill_gems` 等里每个宝石的标签，如 `Lightning`→`闪电`、`AoE`→`效果区域`，同样投票、冲突不入表） |
| `labels` | 表头属性名英文 → 中文（`Cost`→`消耗`、`Cast Time`→`施放时间`、`Tier`→`等阶` 等 17 个） |
| `values` | 表头属性值 `number_key` → `{"zh_hans": 模板}`（`# mana`→`# 点魔力`、`# sec`→`# 秒` 等） |
| `statset_labels` | 技能分段标题（PoB `statSet.label`）英文 → 中文（`Projectile`→`投射物`） |

显示层查法（D02-ui 已接入：PoB `AssistantTerms.lua` 的 `gemTooltip`/`gemTooltipLine`，文件随 `ops/poe2db_update.py` 的 `pob` 步骤导出到 `poe2-assistant/terms/`）：
- 属性行：取当前效果 `effects[grantedEffect.id]`，按 `number_key(英文行)` 查 `lines`（品质行查 `quality`），再用 P03 的 `localize_line(行, 模板, order)` 填入 PoB 的数值。模板里的 `#` 个数和英文行的数值个数一致才会入表；查不到就显示英文。多行属性（行内有 `\n`）整段作为一个键。
- 描述：`effects[id].description.zh_hans`。另附 `en`（编年史英文原文）。78 个效果的 PoB 描述与它不同（PoB 固定版本比 1.0 旧）；显示层只在 PoB 描述与 `en` 去空白后相同时显示中文，不同的保留 PoB 英文（中文描述的是 1.0 机制，和 PoB 算出的数值对不上）。
- 标签、属性名、属性值、分段标题：分别查 `tags`、`labels`、`values`、`statset_labels`（分段标题再退到宝石名、`tags`），查不到就保留英文。表头值查不到时，整行 P10b 回退表能译就交给它（如 `Cast Time: Instant`），否则只译属性名。
- 宝石名不在本表，仍用 `gems.json` 的 `skills[grantedEffectId]`。

入表规则：
- 同一宝石的 us、cn 弹窗按分段、按位置配对，隐藏属性不算。同一键在该宝石所有分段里的中文模板必须一致。
- 中文行的数值必须正好是英文行的数值。顺序不同时带 `order`。正负号按页面写法保留。
- /cn/ 页面上含繁体字的文字一律不用（OpenCC t2s 判断），中文页上没翻译的（无汉字）也不用。
- 同一英文在不同宝石里译法不一，算冲突，不入表，生成时在报告的 `conflicts` 里列出（`scripts/pob_gem_tooltips.py --report <目录>`）。
