from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="仓库轻量 CI 只安装 pytest，Core 检查覆盖知识库模块")

from jkq.kb.importer.analysis import analyze_document

SAMPLES = Path(__file__).resolve().parents[4] / 'tests/fixtures/kb_import'


def test_policy_fields_and_article_ranges():
    text = (SAMPLES / 'policy.txt').read_text()
    result = analyze_document('policy.txt', text)
    assert result['meta'] == dict(title='星汀试验区绿色阅读办法', docNo='星阅发〔2026〕7号',
                                  org='星汀虚构阅读中心', date='2026-03-08', status='现行有效',
                                  url='https://example.invalid/reading', space='policy',
                                  kind='政策文件', expire='')
    assert result['tags'] == ['文化', '绿色低碳']
    assert [c['head'] for c in result['chunks'] if c['head']] == ['第一条', '第十二条']
    for c in result['chunks']:
        assert c['text'] == text[c['start']:c['end']]
        assert c['text'].startswith(c['head'])


def test_each_offset_uses_original_python_indices():
    text = '　第一条 🪴\r\n\r\n　依照第十二条办理。\r\n 第 12 条 单独成条。'
    a, b = analyze_document('', text)['chunks']
    assert a['head'] == '第一条'
    assert b['head'] == '第 12 条'
    assert a['text'] == text[a['start']:a['end']] == '第一条 🪴\r\n\r\n　依照第十二条办理。'
    assert b['text'] == text[b['start']:b['end']] == '第 12 条 单独成条。'


def test_long_plain_and_repeated_paragraphs():
    text = '甲' * 900 + '\n 重复\n 重复'
    chunks = analyze_document('文件名.txt', text)['chunks']
    assert [c['start'] for c in chunks] == [0, 360, 720, 902, 906]
    assert ''.join(c['text'] for c in chunks) == '甲' * 900 + '重复重复'
    assert all(c['text'] == text[c['start']:c['end']] for c in chunks)


def test_metadata_fallback_and_edits():
    text = '第一条 资料。'
    assert analyze_document('阅读办法.pdf', text)['meta']['title'] == '阅读办法'
    edits = dict(title='编辑标题', status='已更新', date='2024年2月29日', org='虚构单位',
                 docNo='星发〔2024〕8号', space='minutes', url='https://example.invalid/edit')
    result = analyze_document('文件', text, source_url='https://example.invalid/raw', overrides=edits)
    assert result['meta'] == {**edits, 'date': '2024-02-29', 'expire': '', 'kind': '会议纪要'}


@pytest.mark.parametrize('edits', [
    [], {'unexpected': '资料'}, {'title': ' '}, {'kind': None}, {'org': 12},
    {'status': '尚未核对'}, {'date': '2025-02-29'}, {'expire': '五月'},
    {'space': 'private'}, {'url': 'file:///文档'}, {'url': 'http://[bad'},
])
def test_invalid_edits_have_chinese_reason(edits):
    with pytest.raises(ValueError, match='[\u3400-\u9fff]'):
        analyze_document('文件', '正文。', overrides=edits)
