#!/usr/bin/env python3
"""Export the P06 XML fixture through the pinned, complete headless PoB engine."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from pob_worker import ROOT, prepare


def validate(directory):
    """Inspect files from disk against fixture facts, including upstream game IDs."""
    summary = {}
    for stage, title, active_id, passive_ids, life in (
        ('leveling', '开荒', 'Metadata/Items/Gem/SkillGemFireball', {'ranger596', 'projectiles15'}, 10),
        ('endgame', '终局', 'Metadata/Items/Gems/SkillGemSpark', {'ranger596', 'projectiles15', 'evasion11'}, 20),
    ):
        path = directory / (stage + '.build')
        raw = path.read_bytes()
        data = json.loads(raw.decode('utf-8'))
        assert data['name'] == 'P06 ' + title
        assert data['author'] == 'P06 验证'
        assert data['description'] == '完整引擎离线导出；双服客户端待验证'
        assert set(data) == {'name', 'author', 'description', 'passives', 'skills', 'inventory_slots'}
        assert isinstance(data['passives'], list) and len(data['passives']) == len(passive_ids)
        passives = {node['id']: node for node in data['passives']}
        assert set(passives) == passive_ids
        if stage == 'leveling':
            assert passives['projectiles15']['additional_text'] == '开荒天赋备注'
            assert all(node['weapon_set'] == 0 for node in passives.values())
        else:
            assert passives['projectiles15']['weapon_set'] == 1
            assert passives['evasion11']['weapon_set'] == 2
            assert passives['evasion11']['additional_text'] == '终局武器组二备注'
        support_id = 'Metadata/Items/Gems/SupportGemArcaneTempo'
        assert data['skills'] == [{
            'id': active_id,
            'additional_text': '开荒火球备注' if stage == 'leveling' else 'Level 20, 20% Quality',
            'support_skills': [support_id if stage == 'leveling' else
                               {'id': support_id, 'additional_text': '终局支援备注'}],
        }]
        assert isinstance(data['inventory_slots'], list) and len(data['inventory_slots']) == 2
        slots = {slot['inventory_id']: slot for slot in data['inventory_slots']}
        assert set(slots) == {'Ring1', 'Ring2'}
        assert all(slot['slot_x'] == 0 for slot in slots.values())
        generated = slots['Ring1']['additional_text']
        assert ('Export Ring' if stage == 'leveling' else 'Endgame Ring') in generated
        assert 'Gold Ring' in generated and f'+{life} to maximum Life' in generated
        assert '<' in generated and '{' in generated  # actual upstream item markup
        assert slots['Ring2']['additional_text'] == ('开荒空槽备注' if stage == 'leveling' else '终局戒指备注优先')
        summary[path.name] = {
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'passives': len(passives), 'skills': len(data['skills']), 'inventory_slots': len(slots),
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', type=Path, metavar='DIRECTORY',
                        help='check saved .build files without running PoB')
    parser.add_argument('--expected-report', type=Path,
                        help='with --verify-only, compare artifact hashes to this report')
    parser.add_argument('--engine', type=Path)
    parser.add_argument('--luajit', type=Path)
    parser.add_argument('--lua-cpath', help='Lua 5.1 native module search path, including lua-utf8')
    parser.add_argument('--output', type=Path, help='existing files are overwritten')
    args = parser.parse_args()
    if args.verify_only is not None:
        summary = validate(args.verify_only)
        if args.expected_report is not None:
            expected = json.loads(args.expected_report.read_bytes())['files']
            for name, artifact in summary.items():
                if artifact['sha256'] != expected[name]['sha256']:
                    parser.error(f'{name}: SHA-256 differs from the expected report')
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.expected_report is not None:
        parser.error('--expected-report requires --verify-only')
    if any(value is None for value in (args.engine, args.luajit, args.lua_cpath, args.output)):
        parser.error('export requires --engine, --luajit, --lua-cpath and --output')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = ROOT / 'tests/fixtures/p06/export.xml'
    fixture_bytes = fixture.read_bytes()
    environment = dict(os.environ, LUA_PATH='../runtime/lua/?.lua;../runtime/lua/?/init.lua;;', LUA_CPATH=args.lua_cpath)
    environment.pop('CI', None)
    with tempfile.TemporaryDirectory(prefix='p06-export-') as temporary:
        engine = Path(temporary) / 'engine'
        pin = prepare(args.engine, engine)
        result = subprocess.run([
            str(args.luajit.resolve(strict=True)), str(ROOT / 'scripts/pob_export_checkpoint.lua'),
            str(fixture), str(ROOT / 'scripts/pob_export.lua'), str(output),
        ], cwd=engine / 'src', env=environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=120)
        (output / 'engine.log').write_text(result.stdout, encoding='utf-8')
        if result.returncode:
            raise SystemExit(result.stdout)
    if fixture.read_bytes() != fixture_bytes:
        raise ValueError("PoB export changed the input fixture")
    report = {'engine_commit': pin, 'fixture_sha256': hashlib.sha256(fixture_bytes).hexdigest(),
              'runtime': {
                  'luajit_sha256': hashlib.sha256(args.luajit.read_bytes()).hexdigest(),
                  'version': subprocess.check_output([str(args.luajit.resolve()), '-v'], text=True).strip(),
              },
              'files': validate(output), 'build_unchanged': True, 'client_imports': {'international': 'pending', 'tencent': 'pending'}}
    (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
