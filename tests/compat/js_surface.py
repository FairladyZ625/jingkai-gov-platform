"""提取零构建 SDK 的导出与对象签名；CI 的 Python 镜像无需 Node。

只解析接口结构，不执行函数体；遇到未知导出写法直接失败，不能静默漏掉公共面。
"""
import ast
import re


def surface(source, require_context=True):
    """提取模块导出与上下文签名。

    require_context=False 用于没有 createContext 的模块（如 /sdk/ui/），此时返回的
    context 为 None；模块若仍声明 createContext 则照常校验它返回公共对象。
    """
    tokens = []

    def quoted(i):
        quote = source[i]
        i += 1
        while i < len(source):
            ch = source[i]
            if ch == '\\':
                i += 2
                continue
            if ch == quote:
                return i + 1
            if quote == '`' and source[i:i + 2] == '${':
                depth, i = 1, i + 2
                while depth:
                    ch = source[i]
                    if ch in "'\"`":
                        i = quoted(i)
                        continue
                    depth += (ch == '{') - (ch == '}')
                    i += 1
                continue
            i += 1
        raise AssertionError('SDK 含未闭合字符串')

    i = 0
    while i < len(source):
        if source[i].isspace():
            i += 1
        elif source[i:i + 2] == '//':
            end = source.find('\n', i)
            i = end if end >= 0 else len(source)
        elif source[i:i + 2] == '/*':
            end = source.find('*/', i + 2)
            assert end >= 0, 'SDK 含未闭合注释'
            i = end + 2
        else:
            start = i
            if source[i] in "'\"`":
                i = quoted(i)
            else:
                match = re.match(r'[A-Za-z_$][\w$]*|=>|\.\.\.|\d+(?:\.\d+)?', source[i:])
                i += len(match[0]) if match else 1
            tokens.append((source[start:i], start, i))
    values = [t[0] for t in tokens]
    pairs, stack = {}, []
    for i, token in enumerate(values):
        if token in ('(', '[', '{'):
            stack.append(i)
        elif token in (')', ']', '}'):
            opening = stack.pop()
            assert values[opening] == {')': '(', ']': '[', '}': '{'}[token]
            pairs[opening] = i
    assert not stack, 'SDK 含未闭合括号'

    def text(start, end):
        return re.sub(r'\s+', ' ', source[tokens[start][1]:tokens[end][2]])

    def expression(start, end):
        if values[start] == '{':
            assert pairs[start] == end
            return obj(start)
        if values[start:start + 3] == ['Object', '.', 'freeze']:
            assert values[start + 3] == '(' and pairs[start + 3] == end, 'Object.freeze 只支持单个参数'
            return expression(start + 4, end - 1)
        if values[start] == 'async':
            return {'async': expression(start + 1, end)}
        if values[start] == '(' and values[pairs[start] + 1] == '=>':
            return text(start, pairs[start])
        if start + 1 <= end and values[start + 1] == '=>':
            return values[start]
        if start == end:
            if values[start].startswith(("'", '"')) or re.fullmatch(r'\d+(?:\.\d+)?', values[start]):
                return ast.literal_eval(values[start])
            assert re.fullmatch(r'[A-Za-z_$][\w$]*', values[start]), '公共值需要显式支持的提取规则：' + text(start, end)
            return 'reference:' + values[start]
        raise AssertionError('公共值需要显式支持的提取规则：' + text(start, end))

    def obj(start):
        result = {}
        i = start + 1
        while i < pairs[start]:
            key = values[i]
            assert re.fullmatch(r'[A-Za-z_$][\w$]*', key), '公共对象属性需要显式名字'
            begin = i + 2 if values[i + 1] == ':' else i
            end = begin
            while end < pairs[start] and values[end] != ',':
                end = pairs[end] + 1 if end in pairs else end + 1
            assert key not in result, '公共对象不能重复定义属性'
            if key != 'preview':
                result[key] = expression(begin, end - 1)
            i = end + 1
        return result

    exports, context = {}, None
    i = 0
    while i < len(tokens):
        if values[i] != 'export':
            i += 1
            continue
        i += 1
        async_ = values[i] == 'async'
        if async_:
            i += 1
        kind, name = values[i:i + 2]
        if kind == 'function':
            args = i + 2
            assert values[args] == '('
            exports[name] = {'signature': text(args, pairs[args]), 'async': async_}
            body = pairs[args] + 1
            if name == 'createContext':
                cursor = body + 1
                while cursor < pairs[body]:
                    if values[cursor:cursor + 2] == ['return', '{']:
                        context = obj(cursor + 1)
                        break
                    cursor = pairs[cursor] + 1 if cursor in pairs else cursor + 1
                assert context is not None, 'createContext 必须显式返回公共对象'
            i = pairs[body] + 1
        elif kind == 'const':
            assert values[i + 2] == '='
            begin = i + 3
            end = begin
            while end + 1 < len(tokens) and values[end + 1] not in (';', 'export'):
                end = pairs[end] if end in pairs else end + 1
            exports[name] = expression(begin, end)
            i = end + 1
        else:
            raise AssertionError('新增导出写法需要补充提取规则：' + kind)
    if require_context:
        assert context is not None
    return {'exports': exports, 'context': context}
