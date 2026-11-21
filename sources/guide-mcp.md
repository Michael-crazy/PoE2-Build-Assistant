# A01 本地 MCP 输入校验检查点

`scripts/guide_mcp.py` 复用官方 Python MCP SDK 的 FastMCP 和现有
`guide_contract.validate_guide`；不自行实现 JSON-RPC 或 MCP 生命周期。
依赖固定为 `mcp==1.30.0`，Python 3.10+（测试脚本用 Python 3.11+ 的 asyncio.timeout）。
SDK 自带依赖由 pip 解析，本轮未制作离线依赖包或 Windows 便携环境。

安装到自行选择的虚拟环境：

```sh
python3 -m venv /tmp/poe2-mcp-venv
/tmp/poe2-mcp-venv/bin/python -m pip install -r requirements-mcp.txt
/tmp/poe2-mcp-venv/bin/python -B scripts/guide_mcp.py
```

入口仅监听进程 stdin/stdout，日志由 SDK 写 stderr；不绑定 TCP 端口。
支持 stdio 的 MCP 客户端可按如下配置启动（替换解释器和仓库绝对路径）：

```json
{
  "mcpServers": {
    "poe2-guide-input": {
      "command": "/tmp/poe2-mcp-venv/bin/python",
      "args": ["-B", "/path/to/PoE2-Build-Assistant/scripts/guide_mcp.py"]
    }
  }
}
```

只注册 `validate_guide_input`，参数为 `{"guide": <完整 v1 JSON>, "confirmation": <可选确认对象>}`。
省略 confirmation 或显式 null 仅查询；提供对象时复用 `validate_confirmation`，
核对完整 context 与明确 selection，过期或非法选择返回工具错误。
公开工具 schema 要求 guide 为 object；字段级规则由现有契约校验器执行。
输入说明和完整自编样本见 [输入契约](guide-input-contract.md) 和 `tests/fixtures/a01/`。
成功结果同时以 MCP 文本 JSON 和 structuredContent 返回，内容与原 CLI 一致；
失败返回 SDK 的 `isError: true` 工具结果，错误调用后会话仍可继续。
工具只读，不访问网络、不读取客户端指定文件、不启动 PoB、不生成或保存 BD。
原文、缺失与推断标记保留；两个 pending 字段也保留，其含义是实际 PoB 生成与
整个 A01 验收未完成，不能当作生成成功。本轮也不解析自由文本或获取真实攻略。

## 验证与环境边界

正常环境：用安装上述依赖的 Python 执行
`python -B -m unittest discover -s tests -p 'test_guide_mcp.py' -v`。
测试实际创建服务子进程，经 SDK stdio 客户端 initialize、list_tools、call_tool；
比对普通/结构化、英文技能歧义/名称-ID 冲突及职业归属交集/冲突、未知树版本七份自编攻略
与原校验器的全部结果，并验证错误及恢复。

某些沙箱环境里线程结果无法及时唤醒事件循环，SDK 的 initialize 会超时。
仅测试可设置 `POE2_MCP_SANDBOX_POLL=1`，在客户端和服务器事件循环添加
10ms 定时唤醒，仍执行实际入口和 SDK stdio 管道，不替换协议、工具或校验器。
生产入口不含该辅助。

后续实际生成仍依赖 P03 版本化名称/ID 映射和完整可加载 BD 样本、固定 fork
加载及 Windows 打开验证；本检查点不输出占位 XML 或伪造技能/树 ID。

离线候选现已接入同一工具返回；规则见 [输入契约](guide-input-contract.md#离线主技能候选返回)。
工具只读取仓库固定索引和 manifest，不接受客户端索引路径或自动解析/确认技能。

职业／升华候选也经同一工具返回，包含缺失／未知树版本状态和职业归属一致性，
规则见 [输入契约](guide-input-contract.md#离线职业升华候选返回)。候选确认入口见文末；不提供生成操作。

天赋节点候选现经同一工具返回，要求显式树版本，保留逐 ID 查询及来源，
规则见 [输入契约](guide-input-contract.md#离线天赋节点候选返回)。
确认入口见下文，不提供生成。

候选查询现附带 `confirmation_context`，绑定原攻略、完整候选快照、索引来源 SHA 与树版本。
确认输入的离线 Python 契约见 [候选确认契约](guide-input-contract.md#离线候选确认契约-v1)。
唯一工具现开放可选 confirmation 对象，required 仍仅 guide；成功新增 candidate_selection，
原攻略、候选及 pending 完整保留。拒绝过期后须重新查询并明确选择，不自动重放。
SDK stdio 测试覆盖省略/null、成功确认、过期来源/攻略、越界节点、错误形状及同会话恢复；
完整文本 JSON 与 structuredContent 均与 Python 校验结果相等。
