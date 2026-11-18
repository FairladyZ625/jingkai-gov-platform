"""知识库文件的正文提取。外部解析器只能由调用方显式注入。"""
import asyncio
import codecs
import io
import re
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_FILE = 8 * 1024 * 1024
MAX_TEXT = 1_000_000
WORD = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class ParseError(ValueError):
    """可在导入预览中展示的解析失败原因。"""


def _body(value):
    if not isinstance(value, str) or not value.strip():
        raise ParseError('没有提取到正文')
    if len(value) > MAX_TEXT:
        raise ParseError('正文超过字数上限')
    if re.search(r'[\x00-\x08\x0e-\x1f\x7f]', value):
        raise ParseError('正文含不可读的控制字符')
    return value.strip()


def _decode(content):
    encodings = ('utf-8-sig', 'gb18030')
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encodings = ('utf-16',)
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ParseError('无法识别文本编码')


def _docx(content):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            info = archive.getinfo('word/document.xml')
            if len(archive.infolist()) > 4096 or info.file_size > MAX_FILE:
                raise ParseError('DOCX 解压内容超过上限')
            xml = archive.read(info)
        root = ET.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError,
            EOFError, zlib.error, LookupError, NotImplementedError) as exc:
        raise ParseError('DOCX 损坏或无法读取正文') from exc
    body = root.find(WORD + 'body')
    if root.tag != WORD + 'document' or body is None:
        raise ParseError('DOCX 缺少正文结构')
    pieces = []
    for paragraph in body.iter(WORD + 'p'):
        line = []
        for node in paragraph.iter():
            if node.tag == WORD + 't':
                line.append(node.text or '')
            elif node.tag in (WORD + 'br', WORD + 'cr'):
                line.append('\n')
            elif node.tag == WORD + 'tab':
                line.append('\t')
        pieces.append(''.join(line))
    return '\n'.join(pieces)


async def _pdf(content):
    if b'%PDF-' not in content[:1024]:
        raise ParseError('PDF 文件头损坏')
    try:
        proc = await asyncio.create_subprocess_exec(
            'pdftotext', '-enc', 'UTF-8', '-nopgbrk', '-', '-',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        raise ParseError('本机无法启动 PDF 解析工具 pdftotext') from exc

    async def read():
        proc.stdin.write(content)
        proc.stdin.close()
        data = bytearray()
        while block := await proc.stdout.read(65536):
            data.extend(block)
            if len(data) > 4 * MAX_TEXT:
                raise ParseError('PDF 正文超过上限')
        if await proc.wait():
            raise ParseError('PDF 损坏、加密或无法读取')
        return data.decode('utf-8')

    try:
        return await asyncio.wait_for(read(), timeout=15)
    except asyncio.TimeoutError as exc:
        raise ParseError('PDF 解析超时') from exc
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.stdout.read()
            await proc.wait()


async def parse_document(name, *, ext='', content=None, text=None,
                         classification='internal', remote_parser=None) -> str:
    if content is None:
        return _body(text)
    if not isinstance(content, bytes) or not content:
        raise ParseError('文件为空或无法读取')
    if len(content) > MAX_FILE:
        raise ParseError('文件超过大小上限')
    ext = (ext or Path(name).suffix).lower().lstrip('.')
    if ext not in ('pdf', 'docx', 'txt', 'html', 'htm'):
        raise ParseError('不支持此文件格式')
    if remote_parser is not None and classification in ('public', 'internal'):
        try:
            result = await asyncio.wait_for(remote_parser(name, ext, content, classification), 15)
        except Exception as exc:
            raise ParseError('外部解析服务未能读取文件') from exc
        if result is not None:
            return _body(result)
    if ext == 'pdf':
        result = await _pdf(content)
    elif ext == 'docx':
        result = await asyncio.to_thread(_docx, content)
    elif ext in ('html', 'htm'):
        try:
            from haiknow_core.aihub.reader import extract
        except ImportError as exc:
            raise ParseError('本机缺少网页正文提取组件') from exc
        try:
            page = extract(_decode(content))
        except (AssertionError, ValueError) as exc:
            raise ParseError('HTML 文档损坏或无法解码') from exc
        if page['truncated']:
            raise ParseError('网页正文超过提取上限')
        result = page['text']
    else:
        result = _decode(content)
    return _body(result)
