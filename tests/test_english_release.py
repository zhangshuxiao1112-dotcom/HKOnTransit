"""English release checks for deliverable text and generated responses."""
import asyncio
from pathlib import Path
import re
from ai.base import AIServiceConfig
from ai.service import AIService

HAN = re.compile(r'[\u3400-\u9fff]')


def test_all_delivered_text_files_are_english():
    root = Path(__file__).resolve().parents[1]
    for path in root.rglob('*'):
        if not path.is_file() or any(p in path.parts for p in ('__pycache__', '.pytest_cache', 'node_modules')):
            continue
        if path.suffix not in ('.py', '.js', '.cjs', '.json', '.html', '.md', '.sh', '.txt', '.example'):
            continue
        assert not HAN.search(path.read_text()), str(path.relative_to(root))
    assert not list(root.glob('live_preview_*.png'))


def test_local_report_summary_is_english_for_chinese_input():
    async def scenario():
        service = AIService(AIServiceConfig(provider='mock'))
        report = await service.structure_community_report('\u8f66\u8f86\u5230\u7ad9')
        assert report.event_type == 'vehicle_arrived'
        assert report.summary == 'A vehicle arrival was reported.'
    asyncio.run(scenario())


def test_non_english_live_response_uses_disclosed_english_fallback():
    async def scenario():
        service = AIService(AIServiceConfig(provider='mock'))
        async def non_english(*args, **kwargs):
            return {'preferences': [{'key': 'less_walking', 'weight': .9, 'rationale': '\u51cf\u5c11\u6b65\u884c'}], 'notes': None}
        service.adapter.extract_intent = non_english
        result = await service.interpret_preferences('Less walking')
        assert result.preferences[0].key == 'less_walking'
        assert not HAN.search(result.model_dump_json())
        assert 'locally' in result.notes
        assert service.last_fallback_reason == 'ValueError'
    asyncio.run(scenario())


def test_route_explanation_stays_english_even_with_requested_chinese():
    async def scenario():
        service = AIService(AIServiceConfig(provider='mock', default_language='zh-Hant'))
        result = await service.explain_route({'summary': '\u51fa\u884c\u65b9\u6848', 'walk_minutes': 3}, language='zh-Hant')
        assert not HAN.search(result.model_dump_json())
        assert result.route_summary == 'Route overview'
    asyncio.run(scenario())
