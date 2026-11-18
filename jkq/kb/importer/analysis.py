"""从同一份正文推断元数据、生成可定位的切片和稳定标签。"""
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ARTICLE = re.compile(r'第[^\S\r\n]*[零〇一二两三四五六七八九十百千万\d]+[^\S\r\n]*条')
DOC_NO = re.compile(r'[\u3400-\u9fff]{1,20}[〔【\[]\d{4}[〕】\]]\s*\d+\s*号')
DATE = re.compile(r'(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?')
STATES = ('现行有效', '即将到期', '已失效', '已更新', '')
KINDS = {'policy': '政策文件', 'enterprise': '企业档案', 'minutes': '会议纪要',
         'rules': '内部制度', 'template': '通知范文'}
TAG_RULES = (
    ('数据要素', '数据券|数据要素|数据交易'), ('人工智能', '人工智能|AI|大模型|智能体'),
    ('机器人', '机器人|具身'), ('生物医药', '医药|医疗器械'), ('人才', '人才'),
    ('金融', '融资|贷款|基金'), ('文化', '文化|书店|阅读'), ('绿色低碳', '绿色|低碳|节能'),
    ('科技创新', '科技创新|研发|孵化'),
)


def _chunks(text):
    chunks = []
    head = ''
    for m in re.finditer(r'[^\r\n]+', text):
        line = m[0].strip()
        if not line:
            continue
        start = m.start() + len(m[0]) - len(m[0].lstrip())
        end = start + len(line)
        article = ARTICLE.match(line)
        if article:
            head = article[0]
        if head and not article and chunks and end - chunks[-1]['start'] <= 360:
            chunk = chunks[-1]
            chunk.update(end=end, text=text[chunk['start']:end])
            continue
        for pos in range(start, end, 360):
            stop = min(pos + 360, end)
            chunks.append(dict(head=head, text=text[pos:stop], start=pos, end=stop))
    return chunks


def _field(text, labels):
    match = re.search(rf'(?m)^[^\S\n]*(?:{labels})[ \t]*[：:][ \t]*([^\r\n]+)', text)
    return match[1].strip() if match else ''


def _iso(value):
    match = DATE.fullmatch(value)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    raise ValueError('日期无效，请填写有效年月日')


def _url(value):
    try:
        parts = urlsplit(value)
        if (parts.scheme in ('http', 'https') and parts.hostname and not parts.username
                and parts.port != 0 and not re.search(r'[\s\\\x00-\x1f]', value)):
            return value
    except ValueError:
        pass
    raise ValueError('来源网址须为有效的 HTTP 或 HTTPS 链接')


def _space(title):
    for pattern, space in (('一企一档|企业档案', 'enterprise'), ('会议|纪要', 'minutes'),
                           ('制度|规程|管理规定|守则', 'rules'), ('通知|简报|请示|函$', 'template')):
        if re.search(pattern, title):
            return space
    return 'policy'


def analyze_document(name, text, *, overrides=None, source_url='') -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError('缺少待分析的正文')
    first = text.lstrip().splitlines()[0].strip()
    title = _field(text, '标题|文件名称')
    if not title and len(first) <= 100 and not ARTICLE.match(first) and not re.search(r'[：:。！？]', first):
        title = first
    title = title or Path(name).stem or '未命名资料'
    space = _space(title)
    docno = DOC_NO.search(text)
    org = _field(text, '发文单位|发布机构|发文机关|发布单位')
    if not org:
        issuer = re.search(r'(?m)^([^\s：:，。]{2,48}(?:局|委员会|中心|办公室))[ \t]*\r?$', text)
        org = issuer[1] if issuer else ''
    issued = DATE.search(_field(text, '日期|发文日期|发布日期') or text)
    try:
        published = _iso(issued[0]) if issued else ''
    except ValueError:
        published = ''
    status = _field(text, '状态|效力状态|有效性')
    url = re.search(r'https?://[^\s<>，。；）]+', _field(text, '来源|来源网址|来源地址|来源链接|来源 ?URL') or text)
    meta = dict(title=title, space=space, kind=KINDS[space], docNo=docno[0] if docno else '',
                org=org, date=published, status=status if status in STATES[:-1] else '现行有效',
                url=source_url or (url[0] if url else ''), expire='')
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError('编辑后的元数据须为对象')
        for key, value in overrides.items():
            if key not in meta or not isinstance(value, str) or len(value) > 2048:
                raise ValueError('元数据字段不受支持或内容无效')
            value = value.strip()
            if key in ('title', 'kind') and not value:
                raise ValueError('标题和资料类型不能为空')
            if key == 'space' and value not in KINDS:
                raise ValueError('未知知识库空间')
            if key == 'status' and value not in STATES:
                raise ValueError('无效的文件状态')
            if key in ('date', 'expire') and value:
                value = _iso(value)
            meta[key] = value
        if 'space' in overrides and 'kind' not in overrides:
            meta['kind'] = KINDS[meta['space']]
    if meta['url']:
        meta['url'] = _url(meta['url'])
    sample = meta['title'] + '\n' + text[:4000]
    tags = [tag for tag, pattern in TAG_RULES if re.search(pattern, sample)][:5]
    return dict(meta=meta, chunks=_chunks(text), tags=tags)
