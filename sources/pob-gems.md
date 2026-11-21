# 固定版本宝石身份与主技能资格索引

`sources/pob-gems.json`（schema_version 1）由 `scripts/index_pob_gems.py` 从 `pob.json`
固定提交的本地 Git 对象生成：`src/Data/Gems.lua`、按 `Modules/Data.lua` 中 skillTypes 顺序加载的
`src/Data/Skills/*.lua`，并记录 SkillsTab/CalcTools 哈希。中文名只从 `data/terms/poe2db-1.0`
的五张宝石表接入。不联网，不执行 Lua，不生成 BD。

```sh
python3 -B scripts/index_pob_gems.py /tmp/poe2-pob-source /tmp/pob-gems.json
cmp sources/pob-gems.json /tmp/pob-gems.json
python3 -B -m unittest discover -s scripts -p 'test_index_pob_gems.py' -v
```

`gems` 每条：PoB 宝石 id、`gameId`/`variantId`（存档写入的游戏身份）、`grantedEffectId`、
`naturalMaxLevel`、附加效果（含 Data.setupGem 按名称注入的 Barbs 触发效果）、
`initializedGrantedEffectIds`（按 grantedEffectDisplayOrder 排序，未定义的效果去掉并列入
`unresolvedAdditionalGrantedEffectIds`）、`primary_player_skill_eligible` 及原因、`names`
（zh_hans/zh_hant，无则 null）和 `term_refs`。Gems.lua 重复键按 Lua 规则取最后一条，保留全部声明位置。

`skills` 每条效果：`support`、`hideFromSideBar`、精确的等级键与对应 `levelRequirement`
（不推断连续范围），以及作为主效果的宝石列表。主技能资格 = 存在主宝石且非 support、非 hideFromSideBar。
未计入 `legacy` 过滤和职业/升华/装备来源限制。

中文名仅在 D01 条目的 `pob` 三元组（gameId、variantId、grantedEffectId）与索引完全一致时接入，
不按英文名匹配；同一宝石多张表名称不一致直接失败。不匹配条目列在 `terms.unjoined`。
当前 966 宝石中 717 有中文名，399 个可作主技能宝石中 178 个有中文名；其余多为升华、物品或
D01 未收录的技能，保留 null，不猜译。

