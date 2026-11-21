# P02 PoB 试算契约

## 常驻试算进程 `trial-server`（供 S01/M07 对接）

浮层用这个进程。启动时加载一次引擎和 BD，之后每次 `evaluate` 在毫秒级返回。LuaJIT 以 ctypes 在 Python 进程内加载：Windows 用固定 PoB 自带的 `runtime/lua51.dll` 与 `lua-utf8.dll`，Linux 用 `~/.local/state/poe2-assistant/p02-runtime` 的 `libluajit.so` 与 `lua-utf8.so`，不需要另装解释器。

```sh
python scripts/assistant.py trial-server --engine <固定引擎根目录> [--build <BD.xml> | --pob-user-dir <PoB 用户目录>]
```

- `--engine`：含 `src/`、`runtime/` 的固定 PoB。可以是 `601768b` 的干净 Git 检出，或带 `.pob-commit` 标记的导出（Windows：`git -C <pinned-pob> archive 601768b src runtime manifest.xml | tar -x -C <目录>`，再写入 `.pob-commit`）。进程会把 cwd 切到 `<engine>/src`，路径参数一律用绝对路径。
- 不给 `--build` 时跟随“PoB 当前打开的 BD”：PoB 正在运行时用它发布的实时快照（含未保存的修改），否则用它打开或最近打开的 BD 文件（见下）。进程只读 BD，不写回。加载时把导入错误的 `X Resistance is ±N%` 改写成 `±N% to X Resistance` 再交给引擎（导入工具把 `-10% to Fire Resistance` 误写成 `Fire Resistance is -10%` 时，PoB 会当成“火抗固定为 -10%”；游戏里没有这种词缀），行数在 `corrected_lines` 返回。
- `python scripts/assistant.py current-build [--pob-user-dir <目录>]` 单独输出定位结果。

**协议**：stdin/stdout 都是 UTF-8 JSON 行，一行一个请求、一行一个响应，按顺序处理。引擎日志只写 stderr。

启动后先输出一行 `{"event":"ready","engine_commit","init_ms","build":{"path","source","build_name","unsaved"},"load_ms"}`；BD 加载失败时没有 `build`，改为 `build_error`，进程照常服务。引擎无法启动时输出 `{"event":"error","error"}` 并退出。

请求（`id` 可选，原样回显）：

- `{"id","cmd":"load","build":"<绝对路径>"}` 固定使用这份 BD；省略 `build` 表示改回跟随 PoB 当前 BD。返回 `path`（实时快照里新建未保存的 BD 为 `null`）、`source`（`explicit`/`live`/`window`/`settings`）、`unsaved`、`build_name`、`corrected_lines`、`weapon_set`、`baseline`、`equipped`（槽位 → 引擎生效装备名）、`skill`。
- `{"id","cmd":"evaluate","item_text":"<PoB 英文装备文本>","slot":"Ring 2"}` `slot` 可省略。每次先检查 BD：实时快照的进程号或序号变了、或 BD 文件的路径、修改时间、大小变了，就重新加载（`reloaded: true`），重载失败返回错误、下次请求再试。

`evaluate` 成功响应：

```json
{"id":1,"ok":true,"reloaded":false,"elapsed_ms":6.8,
 "build":{"path":"...","name":"S2","source":"live","unsaved":true,"corrected_lines":0},
 "item":{"name":"Agony Hold, Gold Ring","base":"Gold Ring","type":"Ring","rarity":"RARE"},
 "skill":{"dps_source":"player","main_skill":"Lightning Spear","minion_skill":null},
 "baseline":{<指标>},
 "slots":[{"slot":"Ring 1","replaced":"旧装备名或 null",
           "displaced":[{"slot":"Weapon 2","name":"..."}],
           "metrics":{<指标>},"delta":{<数值指标之差>}}]}
```

`skill` 说明 DPS 的取法，与 PoB 侧栏一致：主技能是 PoB 里设置的主技能组与主动技能（不自动挑选，也不用 Full DPS）。主技能召唤召唤物（`mainSkill.minion`）时，`dps_source` 为 `minion`，`DPS` 取召唤物的 `CombinedDPS`，`minion_skill` 是召唤物当前计算的技能名；否则 `dps_source` 为 `player`，`DPS` 等于角色的 `CombinedDPS`。PoB 自己比较装备、宝石时也用这个值（`CalcsTab.lua:724`、`GemSelectControl.lua:331`）。主技能是不造成伤害的技能（如 Virtuous Barrier）时，`DPS` 为 0，与侧栏一致。

指标：`DPS`（浮层显示用，见上）、`CombinedDPS`（角色自身，供对照）、`TotalEHP`、`Life`、`EnergyShield`、`Mana`、`FireResist`、`ColdResist`、`LightningResist`、`ChaosResist`（引擎输出的生效抗性，可为负），`attributes.{Str,Dex,Int}.{value,required,gap}`（`gap = max(0, required - value)`，换装后的属性与全身需求），`requirements_met`，`resists.{Fire,Cold,Lightning,Chaos}.{value,max,total,overcap}`（`value` 同上面的生效抗性；`max = Resist + Missing<元素>Resist`，即引擎算出的上限；`total` 为 `ResistTotal`；`overcap` 为 `ResistOverCap`）。`delta` 只含前十项数值。

槽位规则：遍历 PoB 的全部装备槽，`IsItemValidForSlot` 通过，且武器槽属于主技能实际计算的武器组、其他槽在 PoB 中可见（Ring 3 需要额外戒指位天赋，珠宝槽需已点亮）。所以戒指返回 Ring 1/2，单手武器在可双持时返回 Weapon 1/2，珠宝返回每个已点亮的插槽。`replaced` 是该槽引擎生效的原装备；`displaced` 是因换装被引擎移出的其他槽装备（如双手武器挤掉副手），取自引擎计算环境，不自行推断。

失败响应：`{"id","ok":false,"error"}`，例如 `unrecognized item base`、`no active slot accepts this item`、`item cannot go in slot Ring 3`、BD 加载失败、非法 JSON。

**PoB 实时快照**（U02，PoB 端 `src/Modules/AssistantLiveBuild.lua`，后端 `scripts/pob_live.py`）：我们的 PoB 分支在每次重算后（`outputRevision`、未保存状态或 BD 文件变化时）用 `buildMode:SaveDB` 生成与保存时相同的 XML，写到 PoB 用户目录的 `Assistant/live/<进程号>.xml`，不写 BD 文件。第一行是 `<!--poe2-assistant-live {"protocol":"pob-live/1","pid","seq","revision","unsaved","path","name"}-->`，随后是 XML，最后一行 `<!--poe2-assistant-live-end <seq>-->`；两处序号一致才算写完整（不一致时后端最多重读 5 次，间隔 50 ms）。关闭 BD（回列表、换 BD、退出）时整个文件改写为 `{"closed":true}` 的头。只有真实程序发布：headless（测试和试算引擎本身）不写，测试可设全局 `assistantLiveDir` 打开。后端在这些目录里找：`--pob-user-dir`、每个 PoB 窗口的 exe 所在目录和 `../src`、“文档/Path of Building (PoE2)”。只认进程仍在运行、且进程启动时间不晚于文件写入时间（防进程号复用）的快照，多个时取最新写入的；进程已不在的快照文件由后端删除。没有可用快照时退回下面的定位。加载快照同样经过抗性行纠正，`source` 为 `live`。

**PoB 命令通道**（U06，PoB 端 `src/Modules/AssistantCommands.lua`，后端 `scripts/pob_command.py`）：快照的反方向。后端在快照所在用户目录的 `Assistant/commands/` 下写 `<进程号>.json`（先写 `.tmp` 再改名），内容 `{"protocol":"pob-command/1","seq":N,"command":"add-item","item_text":"…"}`；`seq` 取该进程现有命令文件和结果文件里较大的序号加 1。PoB 打开 BD 期间约每 0.25 秒看一次，取走（删除）命令、执行，再把 `{"protocol","seq","status","itemId"|"code","message"}` 写成 `<进程号>.result.json`（同样先写 `.tmp`），`status` 为 `added`、`exists`（列表里已有 `BuildRaw` 完全相同的装备，选中它，不重复加）或 `error`。后端只认序号相同的结果，结果文件留着给下一次定序号。`add-item` 用 `new("Item"):Item(text)` 建装备（不做粘贴时的品质归一），`AddItem(item, true)` 只进装备列表、不穿上，`AddUndoState` 使 BD 显示未保存，并在装备列表里选中（高亮）新装备；不切换页签，不写 BD 文件。
- 找 PoB：只用快照。没有运行中进程的快照 → `pob-not-running`“PoB 未运行，无法加入”；有快照但已 `closed`（在 BD 列表）→ `pob-no-build`。等待中进程退出 → `pob-not-running` 并删掉命令；5 秒内没被取走 → 删掉命令、`pob-timeout`（不会过后突然加入）；已取走则再等 5 秒结果。
- 后台：SimpleGraphic 在窗口不在前台、鼠标不在窗口上时，除非有挂起的 Lua 协程（PoB `Common.lua` 的 `coroutine._list`）或子脚本，否则不跑帧、不进 Lua（`ui_main.cpp` `Frame`，实测后台 0 帧，`PostMessage` 也唤不醒）。所以 PoB 打开 BD 期间保留一个挂起的协程；不在前台时（LuaJIT FFI 比较前台窗口所属进程）每帧后睡 250 ms，约 4 帧/秒。实测打开 BD 的后台 PoB 约占单核 3–6%，最小化同样能取命令；关闭 BD 后释放协程。U02 快照因此在后台也会更新。
- 稀有装备名：P05 文本里稀有名是占位 `Unnamed Rare`，后端换回游戏里的中文原名再发。上游 `sanitiseText` 会把非 ASCII 字节变成 `?` 或拉丁替代字母，我们在其外包一层：CJK 文字（U+2E80–9FFF、AC00–D7AF、F900–FAFF、FF00–FFEF）先替换成占位、处理后放回，所以中文名在保存、重新打开后不变；其他字符照旧。

**当前 BD 定位**（`scripts/pob_current.py`）：PoB 只在退出或保存选项时把 `<Mode mode="BUILD"><Arg string="文件"/><Arg string="名称"/>` 写进 `Settings.xml`，运行中不更新。因此先找 PoB 窗口，标题是 `<BD 名> (<职业>) - Path of Building (PoE2)`，按名称在构筑目录（`Misc@buildPath`，默认 `<用户目录>/Builds`）下找同名 `.xml`，重名取最新；没有窗口或标题无 BD 名时用 `Settings.xml` 的路径。PoB 目录搬过家时，按路径中 `Builds` 之后的部分映射到当前构筑目录。用户目录：便携版是 exe 所在目录（固定 PoB 的验证副本是 `../src`），安装版是“文档/Path of Building (PoE2)”。未保存的新 BD 没有文件，无法试算。

## 一次性试穿（原 v1 契约）

已实现 Python 3 进程适配器及 `scripts/pob_worker.py` / `scripts/pob_worker.lua`。固定引擎与用户目录 LuaJIT/lua-utf8 已完成 Linux 真实试穿。原有 synthetic 夹具仍仅验证协议；真实引擎样本见 `tests/fixtures/p02/real`。Windows 数值一致性、网络隔离与确认保存尚未验收。

## 调用与数据

在仓库根目录运行以下离线演示（worker 脚本使用绝对路径；Windows 可用 `py -3` 启动适配器，worker 命令改用 Python 的绝对路径）：

```sh
python3 -B scripts/pob_trial.py --build tests/fixtures/p02/build.xml --item tests/fixtures/p02/item.txt --slot 'Weapon 1' -- python3 "$PWD/tests/fixtures/p02/worker.py"
```

适配器一次读取 BD XML 和英文 PoB 装备原文，在临时 cwd 启动显式给定的命令，无 shell；stdin 是一份 UTF-8 JSON，关闭 stdin 后等待，默认 30 秒超时。worker 的 stdout 只能输出一份 JSON，日志写 stderr，失败返回非零。当前仅支持直接子进程 worker，不能以另起后台进程的启动器代替。临时 cwd 不是文件系统或网络沙箱；实际 worker 必须禁止联网和写回 BD。未提供保存/确认接口，也未实现市集调用。

请求字段：

- `protocol`: `pob-trial/1`。
- `engine_commit`: 从 `sources/pob.json` 读取的固定 SHA。
- `build_xml`: 完整 XML 内容，保存其中技能、配置、装备组及主技能选择，不传源文件路径。
- `replacement`: `slot` 为 PoB 槽名，`raw_text` 为候选装备原文。合法槽及装备兼容性由真实 worker/PoB 判定，不能静默换槽。

响应字段：`protocol`、`engine_commit` 与请求相同；`request_sha256` 是收到的原始 stdin 字节的 SHA-256（不重新序列化）；`baseline` 和 `replacement` 各包含数值 `CombinedDPS`、`Life`、`EnergyShield`、`Armour`、`Evasion`。值须有限且非负，缺值不能填零。适配器核对协议、版本和摘要，逐指标添加 `delta = replacement - baseline`，不用百分比以避免零基准歧义。`CombinedDPS` 指当前主技能的该 PoB 输出字段，不是 Full DPS；召唤物字段和更多生存指标待扩展。摘要只是关联请求，不能证明 worker 用了正确版本，真实 worker 必须自行核对引擎。

用户目录构建依赖与精确版本见 [runtime 构建](pob-user-runtime.md)。Lua worker 复用上游解析器和计算器；launcher 复制固定引擎到适配器临时目录后 exec LuaJIT。新增 Lua 5.4 桩测试只验证 worker 控制流，未加载 PoB。

## 真实 runtime 完整验收清单（以下保留前轮环境发现）

1. 引擎检出必须为 `601768bd105869618c3d6581b883e5d7aeec91b2`，保留完整 `src/`、`runtime/lua/`、数据文件及 manifest；不改上游源码。本机 `luajit`、`lua`、`busted`、`wine` 均未找到；Docker CLI 在，但无法访问 `/var/run/docker.sock`，没有确认可用容器 runtime。
2. 优先复用该提交的 `Dockerfile` 或 `.github/workflows/test.yml` 环境。Dockerfile 固定 Alpine 3.18、Lua 5.1.5、LuaJIT 提交 `2460b3ff93a1c955de3d62cfc825de7d68dc272e`，LuaRocks 3.7.0、busted 2.2.0-1、luautf8 0.1.6-1；其他构建依赖按原文件安装。不要用系统 Lua 5.4 替代；CI 的 `latest` 镜像未固定，使用前记录镜像 digest。
3. runtime 就绪后先从引擎根目录执行 `busted --lua=luajit ../spec/System/TestMiscCalculator_spec.lua`（`.busted` 自动将 cwd 设为 `src` 并加载 HeadlessWrapper）。直接运行 worker 时 cwd 必须是 `src`，`LUA_PATH='../runtime/lua/?.lua;../runtime/lua/?/init.lua;;'`。这与适配器的临时 cwd 不同，真实 worker 应显式切到固定引擎 src，使用独立用户目录隔离设置；离线初始化和写文件行为仍须检查。
4. 已编写但待引擎验证的 worker：核对 HEAD，加载 `HeadlessWrapper.lua`，`loadBuildFromXML`，等待帧完成，拒绝启动 prompt/加载失败；用 `new("Item"):Item(rawText)` 解析候选并检查槽有效。复用 `build.calcsTab:GetMiscCalculator()`，分别 `calcFunc()` 与 `calcFunc({repSlotName=slot, repItem=item})`，保持同一配置、主技能、武器组；目标武器槽须与 `build.calcsTab.mainEnv.weaponSet` 一致，否则拒绝；不调用 AddItem、SetSelItemId 或保存。响应前再算 baseline，检查原状态未变。stdout 的初始化日志必须重定向到 stderr。不能直接把 Lua 内存地址或缺失输出编码成指标。
5. 用独立可分发真实 BD 和候选创建回归夹具；在禁网环境验证初始化、baseline → replacement → baseline 不变、输入文件哈希不变、双手武器/副手与武器组行为。当前 `tests/fixtures/p02/build.xml` 只验证传输，不能作为这一步的真实 BD。

## Windows 对照（P02 待验收）

使用上述固定 SHA 的完整 fork runtime，记录 runner 提交、引擎 SHA、界面版本、BD/候选文件哈希。在独立副本中打开真实 BD，记录主技能/技能分组、武器组、配置及五项基准指标；用相同槽替换相同候选后记录五项结果，再撤销检查基准恢复。与真实 worker 同一输入的两组原始输出逐字段对照，界面按显示精度舍入比较并保留截图；同时确认主技能没有被自动切换，勿将 Full DPS 当 CombinedDPS。保存原 BD 的哈希应不变。确认后另存副本、关闭重开是后续保存检查点；本轮未实现或验收。
