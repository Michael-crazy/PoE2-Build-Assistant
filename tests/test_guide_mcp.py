"""Exercise the real SDK client/server over subprocess stdio, with authored guides."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from guide_contract import validate_guide
from guide_confirmation import validate_confirmation
from test_guide_confirmation_cli import confirmation_for

# Optional test-only workaround for sandboxes that drop asyncio self-pipe wakeups.
# Apply in both client and spawned server; production entry point stays unchanged.
if os.environ.get('POE2_MCP_SANDBOX_POLL') == '1':
    _run_forever = asyncio.BaseEventLoop.run_forever

    def _polling_run_forever(loop):
        def tick():
            loop.call_later(0.01, tick)
        tick()
        return _run_forever(loop)

    asyncio.BaseEventLoop.run_forever = _polling_run_forever


class GuideMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_contract_and_recovery(self):
        # Bound initialization/calls/shutdown so a transport regression cannot hang CI.
        async with asyncio.timeout(25):
            args = ['-B', str(ROOT / 'scripts/guide_mcp.py')]
            if os.environ.get('POE2_MCP_SANDBOX_POLL') == '1':
                bootstrap = ("import sys,runpy; sys.path.insert(0,sys.argv[1]); "
                             "import test_guide_mcp; sys.path.insert(0,sys.argv[2]); "
                             "runpy.run_path(sys.argv[3],run_name='__main__')")
                args = ['-B', '-c', bootstrap, str(ROOT / 'tests'),
                        str(ROOT / 'scripts'), str(ROOT / 'scripts/guide_mcp.py')]
            params = StdioServerParameters(command=sys.executable, args=args,
                                          env={'POE2_MCP_SANDBOX_POLL': os.environ.get(
                                              'POE2_MCP_SANDBOX_POLL', '0')})
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.serverInfo.name, 'poe2-guide-input')
                    listing = await session.list_tools()
                    self.assertEqual([tool.name for tool in listing.tools], ['validate_guide_input'])
                    self.assertEqual(listing.tools[0].inputSchema['required'], ['guide'])
                    schema = listing.tools[0].inputSchema
                    self.assertIn('confirmation', schema['properties'])
                    for name in ('prose', 'structured', 'english-ambiguous', 'english-conflict',
                                 'class-overlap', 'class-conflict', 'class-unknown-tree'):
                        guide = json.loads((ROOT / f'tests/fixtures/a01/{name}.json').read_text())
                        result = await session.call_tool('validate_guide_input', {'guide': guide})
                        self.assertFalse(result.isError)
                        candidates = result.structuredContent['main_skill_candidates']
                        self.assertEqual(candidates['confirmation'], 'pending')
                        if name == 'english-ambiguous':
                            self.assertEqual(candidates['name']['status'], 'ambiguous')
                        elif name == 'english-conflict':
                            self.assertEqual(candidates['name_id_consistency'], 'conflict')
                        classes = result.structuredContent['class_ascendancy_candidates']
                        self.assertEqual(classes['confirmation'], 'pending')
                        if name in ('class-overlap', 'class-conflict'):
                            self.assertEqual(classes['class_ascendancy_consistency'], name.removeprefix('class-'))
                        elif name == 'class-unknown-tree':
                            self.assertEqual(classes['status'], 'unknown_tree_version')
                        else:
                            self.assertEqual(classes['status'], 'missing_tree_version')
                        self.assertEqual(result.structuredContent, validate_guide(guide))
                        self.assertEqual(json.loads(result.content[0].text), validate_guide(guide))
                    from test_guide_node_candidates import guide as node_guide
                    for version, status in [('0_1', 'ready'), ('0_5', 'ready'),
                                            (None, 'missing_tree_version'),
                                            ('unknown', 'unknown_tree_version')]:
                        guide = node_guide(version, (4, 999999))
                        result = await session.call_tool('validate_guide_input', {'guide': guide})
                        self.assertFalse(result.isError)
                        output = result.structuredContent
                        self.assertEqual(output, validate_guide(guide))
                        self.assertEqual(json.loads(result.content[0].text), output)
                        nodes = output['passive_node_candidates']
                        self.assertEqual(nodes['status'], status)
                        self.assertEqual(nodes['confirmation'], 'pending')
                        self.assertEqual(output['guide'], guide)
                        if status == 'ready':
                            self.assertEqual(nodes['nodes'][1]['status'], 'not_found')
                        else:
                            self.assertIsNone(nodes['nodes'])
                    guide = json.loads((ROOT / 'tests/fixtures/a01/confirmation-guide.json').read_text())
                    query = await session.call_tool('validate_guide_input', {'guide': guide})
                    self.assertFalse(query.isError)
                    baseline = query.structuredContent
                    confirmation = confirmation_for(baseline)
                    before = deepcopy((guide, confirmation))

                    async def confirm(value, error=None):
                        result = await session.call_tool('validate_guide_input',
                                                         {'guide': guide, 'confirmation': value})
                        if error:
                            self.assertTrue(result.isError)
                            self.assertIn(error, result.content[0].text)
                        else:
                            self.assertFalse(result.isError)
                            output = result.structuredContent
                            expected = (validate_guide(guide) if value is None else
                                        validate_confirmation(guide, value))
                            self.assertEqual(output, expected)
                            self.assertEqual(json.loads(result.content[0].text), expected)
                            self.assertEqual({k: v for k, v in output.items()
                                              if k != 'candidate_selection'}, baseline)
                        return result

                    await confirm(confirmation)
                    await confirm(None)
                    stale = deepcopy(confirmation)
                    stale['context']['sources']['skills']['commit'] = '0' * 40
                    await confirm(stale, 'stale or mismatched')
                    await confirm(confirmation)  # same session recovers after a stale input
                    bad_selection = deepcopy(confirmation)
                    bad_selection['selection']['passive_node_ids'] = [999999]
                    await confirm(bad_selection, 'not in original candidates')
                    await confirm({}, 'confirmation')
                    await confirm('invalid', 'confirmation')
                    await confirm(confirmation)
                    self.assertEqual((guide, confirmation), before)
                    guide['source']['text'] += '\nAuthored revision.'
                    await confirm(confirmation, 'stale or mismatched')
                    query = await session.call_tool('validate_guide_input', {'guide': guide})
                    self.assertFalse(query.isError)
                    baseline = query.structuredContent
                    confirmation = confirmation_for(baseline)
                    await confirm(confirmation)
                    bad = deepcopy(guide)
                    bad['schema_version'] = 2
                    result = await session.call_tool('validate_guide_input', {'guide': bad})
                    self.assertTrue(result.isError)
                    self.assertIn('schema_version: expected 1', result.content[0].text)
                    result = await session.call_tool('validate_guide_input', {})
                    self.assertTrue(result.isError)
                    # A rejected call must not poison the session or change subsequent results.
                    result = await session.call_tool('validate_guide_input', {'guide': guide})
                    self.assertFalse(result.isError)
                    self.assertEqual(result.structuredContent, validate_guide(guide))


if __name__ == '__main__':
    unittest.main(verbosity=2)
