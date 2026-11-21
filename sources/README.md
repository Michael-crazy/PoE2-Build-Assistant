# PoB 源码基线

`pob.json` 固定 PoB fork `dev` 分支上的基线提交。`branch` 记录来源，获取时只使用完整 `commit`，不跟随分支更新。我们对 PoB 和 EE2 的改动在专用分支 `poe2-assistant` 上（`pob-branch.json`、`ee2.json`），补丁格式和变基检查见 [pob-branch.md](pob-branch.md)。

Linux 需要 Git 和 Python 3，在项目根目录运行：

```sh
python3 scripts/fetch_pob.py /tmp/poe2-pob-source
git -C /tmp/poe2-pob-source rev-parse HEAD
```

目标目录必须不存在；重复获取请指定新目录。脚本浅获取指定提交，核对 HEAD 后保留 detached HEAD 源码目录；失败清理临时检出，不覆盖现有目录。源码放在仓库外，不提交第三方源码。本步骤只获取 Git 源码，不安装运行环境或下载发布包。

获取后 HEAD 应为 `601768bd105869618c3d6581b883e5d7aeec91b2`（detached HEAD，工作树干净）。该版本的运行时、构建及 P02 源码复用线索见 [pob-runtime.md](pob-runtime.md)。

技能 ID／英文名离线索引见 [pob-skills.md](pob-skills.md)；数据为 [pob-skills.en.json](pob-skills.en.json)，与 `pob.json` 固定提交对应，作为 P03 映射起点。
宝石身份与主技能资格索引见 [pob-gems.md](pob-gems.md)；数据为 [pob-gems.json](pob-gems.json)。
