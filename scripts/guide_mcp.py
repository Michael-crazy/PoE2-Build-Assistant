#!/usr/bin/env python3
"""Local stdio MCP access to the authored guide input contract (no PoB generation)."""
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from guide_contract import validate_guide
from guide_confirmation import validate_confirmation


server = FastMCP(
    'poe2-guide-input',
    instructions='Validate authored guide JSON and query pinned offline skill, class, ascendancy and passive node candidates. Optionally validate explicit candidate selections. Does not parse prose or generate PoB builds.',
)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                         openWorldHint=False))
def validate_guide_input(guide: dict[str, Any],
                         confirmation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate guide-input-contract v1; preserve source, missing and inferred fields.

    Pass the complete authored guide JSON as guide, including schema_version,
    source and fields. Success is input validation only; PoB generation and
    overall MCP acceptance remain pending. All candidates require confirmation;
    class/ascendancy and passive node queries require an explicit indexed tree version.
    Optional confirmation accepts the complete confirmation v1 JSON with the query
    context and explicit selection. Omitted/null means query only. Stale context
    requires a fresh query and choice. Validated choices are recorded separately;
    original fields and candidate pending states remain unchanged.
    Invalid input returns an MCP tool error.
    """
    if confirmation is None:
        return validate_guide(guide)
    return validate_confirmation(guide, confirmation)


if __name__ == '__main__':
    server.run(transport='stdio')
