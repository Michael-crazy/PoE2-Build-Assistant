"""Print how to add this package's POBG (an MCP server on stdio) to common AI clients, with this
package's real paths; the same text is saved to MCP配置.txt next to 显示MCP配置.cmd.

Snippets follow each client's own documentation (read 2026-11-21, see handoff/A01.md).
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
NAME = "pobg"


def server():
    """The command and arguments every client starts."""
    return {"command": str(PACKAGE / "python" / "python.exe"), "args": [str(HERE / "run_pobg.py")]}


def text():
    s = server()
    python, launcher = s["command"], s["args"][0]

    def block(obj):
        return json.dumps(obj, ensure_ascii=False, indent=2)

    stdio = {NAME: {"type": "stdio", **s}}
    sections = [
        ("通用（任何支持本地 stdio MCP 的 AI 客户端）",
         f"名称：{NAME}\n类型：stdio（本地命令）\n命令：{python}\n参数：{launcher}\n"
         "不需要环境变量。JSON 配置里路径的反斜杠要写成两个（下面的示例已经写好）。"),
        ("Claude Code（终端里运行一行）",
         f'claude mcp add --scope user {NAME} -- "{python}" "{launcher}"'),
        ("Claude 桌面版（设置 → 开发者 → 编辑配置，打开 claude_desktop_config.json，"
         "把下面这段并入 \"mcpServers\"，然后完全退出并重开 Claude）",
         block({"mcpServers": {NAME: s}})),
        ("Cursor（用户级 %USERPROFILE%\\.cursor\\mcp.json，或项目里的 .cursor\\mcp.json）",
         block({"mcpServers": stdio})),
        ("VS Code（GitHub Copilot 代理模式；命令面板“MCP: Open User Configuration”打开 mcp.json；"
         "注意顶层键是 servers）",
         block({"servers": stdio})),
        ("Gemini CLI（终端里运行一行；或把 Claude 桌面版那段 mcpServers 写进 %USERPROFILE%\\.gemini\\settings.json）",
         f'gemini mcp add --scope user {NAME} "{python}" "{launcher}"'),
        ("Codex CLI（终端里运行一行；或写进 %USERPROFILE%\\.codex\\config.toml）",
         f'codex mcp add {NAME} -- "{python}" "{launcher}"\n\n'
         f"[mcp_servers.{NAME}]\ncommand = '{python}'\nargs = ['{launcher}']"),
        ("ChatGPT 桌面版（设置 → MCP servers → Add server，类型选 STDIO；与 Codex 共用上面的 config.toml，"
         "两处加一次即可）",
         f"名称：{NAME}\n启动命令：{python}\n参数：{launcher}\n路径照原样填，不加引号、不双写反斜杠。保存后按提示重启。"),
        ("Cherry Studio（设置 → MCP → MCP 服务器 → 添加，选本地/STDIO 服务器）",
         f"名称：{NAME}\n命令：{python}\n参数：{launcher}\n保存后打开开关，看状态和工具列表是否出来。"),
    ]
    lines = ["PoE2 助手 · POBG 的 MCP 配置", "",
             "POBG 是本地 stdio MCP 服务，任何支持本地 MCP 的 AI 客户端都能用。按你用的客户端照下面做一次，"
             "然后重启客户端，用中文问技能、天赋、词缀，或“我 PoB 里当前 BD 的 DPS 和抗性”。",
             "移动了这个文件夹，要重新运行“显示MCP配置.cmd”并更新配置。", ""]
    for title, body in sections:
        lines += [f"== {title}", body, ""]
    lines += ["网页版 ChatGPT、网页版 Claude 等只能连远程（HTTPS）MCP，用不了本地的 POBG。"]
    return "\n".join(lines) + "\n"


def main():
    output = text()
    (PACKAGE / "MCP配置.txt").write_text(output, encoding="utf-8-sig")
    sys.stdout.write(output)
    print("（以上内容已保存到 MCP配置.txt）")


if __name__ == "__main__":
    main()
