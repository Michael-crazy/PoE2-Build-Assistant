# P02 Linux 用户目录 runtime 构建

在 Linux 上跑真实引擎测试需要 LuaJIT 和 `lua-utf8.so`，不需要安装系统包。约定放在 `~/.local/state/poe2-assistant/p02-runtime/`（`LuaJIT/src/luajit`、`lua-utf8.so`），运行时设 `LUA_CPATH="$HOME/.local/state/poe2-assistant/p02-runtime/?.so;;"`。Windows 直接用固定 PoB 自带的 `runtime/lua51.dll` 与 `lua-utf8.dll`。以下是构建步骤和验收清单。

依据引擎 `601768bd105869618c3d6581b883e5d7aeec91b2` 的 Dockerfile、`.busted`、HeadlessWrapper、Modules/Common.lua。此计划不修改系统包，不使用 Docker socket，不发布。当前仅确认 `cc`、`make`、`git`、`tar`、`curl`、`unzip`、`cmake` 可执行；未找到 Lua 5.1/LuaJIT/LuaRocks 源码或可执行文件，readline 头文件未发现。下载探测 `curl -I --connect-timeout 3 --max-time 5 https://www.lua.org/ftp/lua-5.1.5.tar.gz` 返回 `Could not resolve host: www.lua.org`。联网恢复前不能构建或做引擎验证。

## 固定版本与构建范围

| 组件 | 固定版本 | 用途 |
|---|---|---|
| PoB fork | `601768bd105869618c3d6581b883e5d7aeec91b2` | 源码、数据、dkjson、sha2、xml |
| LuaJIT | `2460b3ff93a1c955de3d62cfc825de7d68dc272e` | worker 的实际解释器、5.1 ABI 和头文件 |
| LuaRocks | `3.7.0` | 在独立前缀构建 Lua C 模块 |
| luautf8 | `0.1.6-1` | `require('lua-utf8')`，C 编译器及 Lua 5.1 头文件 |
| busted | `2.2.0-1` | 上游 MiscCalculator spec；不属于 worker 运行依赖 |
| Lua | `5.1.5` | Dockerfile 的引导解释器；以下直接用 LuaJIT，无须构建它 |

Dockerfile 还使用 Alpine 3.18、readline-dev、build-base、tar、git、cmake、curl、unzip、openssl。EmmyLuaDebugger 1.7.1、cluacov 0.1.2-1 和 luacov-coveralls 0.2.3-1 只用于调试/覆盖率，本检查点不需要。LuaJIT 默认构建不需要 readline；不以系统 Lua 5.2/5.4 或 Windows DLL 代替。用户目录需能编译 C、链接共享库并运行产物；若工具链缺失则继续阻塞，不安装系统包。

## 用户目录命令（联网环境预备源码，Linux 本地构建）

所有下载在有网络的环境完成后也可私下传递到 Linux。工作目录内准备：LuaJIT 完整 Git checkout、`luarocks-3.7.0.tar.gz`、`luautf8-0.1.6-1.src.rock`；来源分别为 `https://github.com/LuaJIT/LuaJIT`、`https://luarocks.org/releases/luarocks-3.7.0.tar.gz`、`https://luarocks.org/luautf8-0.1.6-1.src.rock`。保留下载文件 SHA-256、完整来源与构建日志。此处未取得文件，不能预先声称已核对内容哈希。

```sh
# 在含上述源码的目录执行；POB_RUNTIME 可指向工作区的 .local-runtime。
export POB_RUNTIME="$PWD/.local-runtime/p02"
mkdir -p "$POB_RUNTIME"
test "$(git -C LuaJIT rev-parse HEAD)" = 2460b3ff93a1c955de3d62cfc825de7d68dc272e
test -z "$(git -C LuaJIT status --porcelain)"
make -C LuaJIT PREFIX="$POB_RUNTIME"
make -C LuaJIT install PREFIX="$POB_RUNTIME"
tar xf luarocks-3.7.0.tar.gz
cd luarocks-3.7.0
./configure --prefix="$POB_RUNTIME" --with-lua="$POB_RUNTIME" --lua-version=5.1 --with-lua-interpreter=luajit --with-lua-include="$POB_RUNTIME/include/luajit-2.1" --with-lua-lib="$POB_RUNTIME/lib"
make
make install
cd ..
export PATH="$POB_RUNTIME/bin:$PATH"
export LD_LIBRARY_PATH="$POB_RUNTIME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
luarocks --tree="$POB_RUNTIME/rocks" install ./luautf8-0.1.6-1.src.rock
# LuaRocks 在此输出用户 tree 的 LUA_PATH/LUA_CPATH；之后执行 worker 时仍需这些变量。
eval "$(luarocks --tree="$POB_RUNTIME/rocks" path)"
luajit -e 'assert(require("lua-utf8")); print(jit.version)'
```

若 checkout 的 LuaJIT 头文件目录不同，以 `make install` 结果为准并记录配置；不能混用系统头文件。版本和命令来自固定上游的构建方式，但本机未执行，配置成功、模块 ABI 与引擎启动都待验证。

busted 的传递依赖没有在上游 Dockerfile 锁定。首次联网可用 `luarocks --tree="$POB_RUNTIME/rocks" install busted 2.2.0-1 --pin` 解析安装，随后记录 `luarocks list --porcelain`，收齐每个解析版本的 source rock、rockspec、`luarocks.lock` 和 SHA-256。必须在空用户前缀断网重建成功，才能称测试环境可复现；当前不能声称 busted 的依赖闭包已锁定。worker 最小运行闭包只有固定 LuaJIT、luautf8 和固定 PoB 源码中的 Lua 模块，不依赖 busted。

## 运行与验收顺序

1. 先 `cd /tmp/poe2-pob-source`，运行 `busted --lua=luajit ../spec/System/TestMiscCalculator_spec.lua`；`.busted` 自动进入 src。保存实际版本、模块清单与日志；记录 spec 的独立验证结果。当前最小 runtime 未安装 busted，本轮直接调用真实 worker 验证计算。
2. 使用可分发的真实 `PathOfBuilding2` XML 和英文装备文本（当前 synthetic XML 不可用），在助手仓库根执行：

```sh
python3 -B scripts/pob_trial.py --timeout 120 --build /absolute/real-build.xml --item /absolute/item.txt --slot 'Weapon 1' -- python3 "$PWD/scripts/pob_worker.py" --engine /tmp/poe2-pob-source --luajit "$POB_RUNTIME/bin/luajit"
```

3. launcher 校验干净固定 SHA，复制 src/runtime/manifest 到适配器临时 cwd（约 442 MiB），随后 exec LuaJIT；适配器超时直接终止解释器并清理副本。不要单独从仓库根启动 launcher，它会留下 engine-* 副本。不使用硬链接，不把源 BD 路径传给 worker。
4. worker 不调用保存，阻止后台子脚本、URL 和初始化后的下载/更新 API；这些是应用级限制，**不是网络沙箱**。仍需断网环境实测初始化、候选、基准恢复及原文件哈希。初始化写入若发生，只应落在副本；尚未验证所有路径。
5. 核对主技能、技能组、配置、装备组、武器组与界面一致；验证双手/副手例外、错误 XML、不兼容槽、启动错误；最后完成契约文档中的 Windows 对照。Lua 5.4 桩测试不能替代这些检查。
