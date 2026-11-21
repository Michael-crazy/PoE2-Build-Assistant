# 参与开发

感谢你愿意帮忙！提问题、报 bug 请用 Issue（有“问题反馈”和“功能建议”两个模板），讨论想法可以去 Discussions。

## 分支与 PR

- `main` 受保护：不能直接推送，所有改动都经 PR 合入，CI（`.github/workflows/test.yml`）通过后才能合并。
- 从 `main` 开分支，名字随意但要看得出内容，例如 `fix/overlay-resist`、`feat/tencent-currency`。
- 一个 PR 只做一件事；提交消息第一行用简短英文或中文说明做了什么，有对应 Issue 就写上 `#编号`。
- 改 PoB 或游戏内浮层的，请到对应 fork（[PathOfBuilding-PoE2](https://github.com/Michael-crazy/PathOfBuilding-PoE2)、[Exiled-Exchange-2](https://github.com/Michael-crazy/Exiled-Exchange-2)）的 `poe2-assistant` 分支提 PR。那里的规则见 [sources/pob-branch.md](sources/pob-branch.md)：新逻辑放新文件，上游文件只改调用点的少数几行，不重排、不格式化上游代码，保持 LF。

## 跑测试

需要 Python 3.12（与安装包一致）。快速测试只用标准库，不需要 PoB 引擎和网络，CI 跑的就是这些：

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
python3 -B -m unittest discover -s ops -p 'test_*.py'
```

需要真实 PoB 引擎的测试在没有引擎时会自动跳过（输出里是 `skipped`）。要跑完整检查：

1. 按 [sources/README.md](sources/README.md) 取固定版本的 PoB 源码到 `/tmp/poe2-pob-source`，或把环境变量 `POB_ENGINE` 指向 PoB fork 的检出；
2. Linux 按 [sources/pob-user-runtime.md](sources/pob-user-runtime.md) 准备 LuaJIT 与 lua-utf8；
3. 再跑上面两条命令，被跳过的引擎测试就会执行。

PoB 或 EE2 分支变基后的整体回归用 `python3 -B ops/rebase_check.py --work <临时目录> --pob-suite`（需要 Node 22；两个 fork 的裸仓库默认在 `~/git/PathOfBuilding-PoE2.git`、`~/git/Exiled-Exchange-2.git`，即 `sources/pob-branch.json`、`sources/ee2.json` 的 `home`；耗时较长）。MCP 测试（`tests/test_guide_mcp.py`）需要先 `pip install -r requirements-mcp.txt`。

## 术语只用编年史

- 游戏术语（技能、天赋、装备、基底、词缀、通货、职业等）**只用[流放编年史 PoE2DB](https://poe2db.tw/cn/) 的译名**，不自行翻译，也不用其他网站或机翻的说法。数据在 `data/terms/poe2db-1.0/`，由 `ops/poe2db_update.py` 更新。
- 编年史没有、只在 PoB 里出现的界面文字，在 `data/terms/pob-ui/overrides.json` 里添加并注明来源。
- 新增或修改的数据要保留来源字段；不要手改生成出来的表，改生成脚本后重新生成。
- `data/` 下编年史派生数据为 CC BY-NC-SA 3.0（见 [data/DATA-LICENSE.md](data/DATA-LICENSE.md)），提交即表示你同意你对这些数据的修改按同一许可发布；代码按 MIT。

## 提交前跑隐私检查

```sh
python3 -B ops/check_public.py
```

它会扫描分享码、openid、角色 ID、账号名、登录 Cookie（如 `POESESSID`）、本机路径（`C:\Users\…`、`/home/…`）、邮箱和过大的文件，发现问题时退出码为 1。

- 测试夹具里的真实数据必须先脱敏：国服角色用 `python3 -B scripts/wegame_import.py anonymise` 去掉账号、openid、角色名和分享码。
- 不要提交自己的 BD 存档、日志、Cookie 或截图里带账号信息的内容。
- 本机路径在文档里写成 `<PoB 目录>`、`$HOME/...` 这样的占位。
