"""Check corpus provenance and retrieval, not generated-answer quality."""
from pathlib import Path

from backend.knowledge import CHUNKS, DOCUMENTS, load_manuals, retrieve


def test_synthetic_manuals_have_complete_traceable_sections():
    manuals = [d for d in DOCUMENTS if d['source_type'] == 'synthetic_demo_manual']
    assert len(manuals) == 4
    assert len({d['id'] for d in manuals}) == 4
    for manual in manuals:
        assert manual['is_synthetic'] is True
        assert len(manual['text']) > 2000
        sections = [c for c in CHUNKS if c['id'] == manual['id']]
        assert len(sections) == 12
        source = Path(manual['source_path']).read_text(encoding='utf-8').splitlines()
        for section in sections:
            assert section['machine_models'] == ['PF-VMC850-DEMO']
            assert source[section['line_start'] - 1] == '## ' + section['section']
            assert section['text'] == '\n'.join(source[section['line_start']:section['line_end']]).strip()


def test_manual_retrieval_preserves_provenance_and_specific_topics():
    examples = [
        ('刀庫位置確認未完成 DEMO-ATC-01', 'PF-MAN-ATC-002'),
        ('冷卻泵過濾段 DEMO-CL-FLT-01', 'PF-MAN-COOLANT-003'),
        ('定位量測工具校驗行程區段', 'PF-MAN-FEED-004'),
        ('主軸潤滑 DEMO-SP-01', 'PF-MAN-SPINDLE-001'),
    ]
    for question, expected in examples:
        matches = [r for r in retrieve(question, limit=5) if r['id'] == expected]
        assert matches, question
        assert all(r['is_synthetic'] and r['version'] == '1.0' and r['line_start'] > 0 for r in matches)


def test_manual_loader_rejects_paths_outside_corpus(tmp_path):
    (tmp_path / 'manifest.json').write_text(
        '{"manuals":[{"id":"bad","file":"../outside.md"}]}', encoding='utf-8')
    import pytest
    with pytest.raises(ValueError, match='inside'):
        load_manuals(tmp_path)
