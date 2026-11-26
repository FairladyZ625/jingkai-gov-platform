"""岗位的只读检索适配；默认事项列表仍保留原子串检索。"""
import re

from .policy_catalog import list_items

# 仅移除问法，不推断企业身份或补造政策条件；不能定位主题时请用户给出名称。
QUESTION_WORDS = (
    '需要准备', '申请条件', '申报条件', '申报期限', '截止时间', '什么时候', '什么时间',
    '准备什么', '有哪些', '有什么', '需要什么', '是否可以', '可以申请', '能申请', '能申报',
    '如何申请', '怎么申请', '怎样申请', '请问', '帮我', '查询', '查一下', '了解', '我们',
    '公司', '企业', '什么', '哪些', '需要', '准备', '申请', '申报', '条件', '材料', '期限',
    '政策', '支持', '补贴', '奖励', '扶持', '手续', '流程', '要求', '办理', '时候', '是否',
    '然后', '下一步', '那', '这个', '这项', '还有', '它', '该', '的', '是', '呢', '吗', '么',
)
QUESTION_PATTERN = re.compile('|'.join(map(re.escape, sorted(QUESTION_WORDS, key=len, reverse=True))))


def search_question(question: str, object_type: str, window: str) -> dict:
    result = list_items('', object_type, window)
    text = question.casefold()
    # 已明确的事项编号优先，避免把同一句里的其他描述当作另一个查询目标。
    explicit = [row for row in result['items'] if re.search(r'(?<![a-z0-9_-])' + re.escape(row['id'].casefold())
                                                         + r'(?![a-z0-9_-])', text)]
    terms = [part for part in re.split(r'[^\w\u4e00-\u9fff-]+', QUESTION_PATTERN.sub(' ', text))
             if len(part) >= 2]
    def searchable(row):
        return ' '.join((row['title'], row.get('sub', ''), row['docTitle'], row.get('original', ''),
                         *row.get('keywords', []))).casefold()

    matches = explicit or [row for row in result['items'] if terms and any(term in searchable(row) for term in terms)]
    if not matches:
        # “实体书店房租”这类连写只回退到目录已有的具体关键词组合，且须同时落在同一条款。
        anchors = {word.casefold() for row in result['items'] for word in row.get('keywords', [])
                   if len(word) >= 2 and word not in QUESTION_WORDS and word.casefold() in text}
        if len(anchors) >= 2:
            matches = [row for row in result['items'] if all(word in searchable(row) for word in anchors)]
    return {**result, 'items': matches, 'total': len(matches),
            'queryState': 'searched' if explicit or terms else 'clarify'}
