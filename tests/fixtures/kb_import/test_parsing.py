import asyncio
import io
from pathlib import Path
import shutil
from unittest.mock import AsyncMock
import zipfile

import pytest

from jkq.kb.importer.parsing import MAX_FILE, ParseError, parse_document

SAMPLES = Path(__file__).parent


@pytest.mark.parametrize('ext', ['pdf', 'docx', 'txt', 'html'])
def test_actual_policy_file(ext):
    if ext == 'pdf' and not shutil.which('pdftotext'):
        pytest.skip('本地 PDF 正文提取需要 Poppler')
    if ext == 'html':
        pytest.importorskip('fastapi', reason='core reader 通过平台 SDK 依赖 FastAPI')
    path = SAMPLES / ('policy.' + ext)
    body = asyncio.run(parse_document(path.name, content=path.read_bytes(), text='替代文字'))
    assert body.splitlines() == (SAMPLES / 'policy.txt').read_text().splitlines()


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'gb18030', 'gbk', 'utf-16'])
def test_text_encodings_and_paste(encoding):
    body = '第一条 导入正文。\n第二条 保留段落。'
    assert asyncio.run(parse_document('未命名', ext='.TXT', content=body.encode(encoding))) == body
    assert asyncio.run(parse_document('粘贴', text=body)) == body


@pytest.mark.parametrize('name,content,reason', [
    ('坏.pdf', b'%PDF-1.7\n', 'PDF'), ('坏.docx', b'badzip', 'DOCX'),
    ('空.txt', b' \r\n', '正文'), ('损坏.txt', b'\xff', '编码'),
    ('二进制.txt', b'abc\x00', '控制字符'), ('空.pdf', b'', '为空'),
    ('不支持.xls', b'content', '格式'), ('过大.txt', b'a' * (MAX_FILE + 1), '上限'),
], ids=['pdf', 'docx', 'blank', 'encoding', 'binary', 'empty', 'unsupported', 'large'])
def test_file_failure_cannot_use_supplied_text(name, content, reason):
    with pytest.raises(ParseError, match=reason):
        asyncio.run(parse_document(name, content=content, text='不能覆盖原文件'))


def test_docx_decompression_limit():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', b'x' * (MAX_FILE + 1))
    with pytest.raises(ParseError, match='解压'):
        asyncio.run(parse_document('超限.docx', content=data.getvalue()))


@pytest.mark.parametrize('classification', ['confidential', '未定义', None])
def test_restricted_file_never_calls_remote(classification):
    remote = AsyncMock(return_value='模拟服务结果')
    content = (SAMPLES / 'policy.docx').read_bytes()
    result = asyncio.run(parse_document('样本.docx', classification=classification,
                                        content=content, remote_parser=remote))
    assert '第十二条' in result
    remote.assert_not_called()


def test_allowed_parser_receives_raw_file():
    remote = AsyncMock(return_value='模拟服务结果')
    content = (SAMPLES / 'policy.docx').read_bytes()
    result = asyncio.run(parse_document('样本.docx', content=content, classification='public',
                                        remote_parser=remote))
    remote.assert_awaited_once_with('样本.docx', 'docx', content, 'public')
    assert result == '模拟服务结果'


def test_pdf_missing_poppler(monkeypatch, tmp_path):
    monkeypatch.setenv('PATH', str(tmp_path))
    with pytest.raises(ParseError, match='pdftotext'):
        asyncio.run(parse_document('样本.pdf', content=(SAMPLES / 'policy.pdf').read_bytes()))


def test_html_without_body_text():
    pytest.importorskip('fastapi')
    with pytest.raises(ParseError, match='正文'):
        asyncio.run(parse_document('空.html', content=b'<title>title</title><script>x</script>'))
