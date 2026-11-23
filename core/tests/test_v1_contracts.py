"""contracts/v1 所有 JSON 样例都与真实服务核对。"""
import json
import re

import pytest

from conftest import ROOT
from test_platform import login

CASES = []
for path in sorted((ROOT / 'tests/fixtures/v1').glob('*.json')):
    if path.name != 'conventions.json':
        CASES.extend(json.loads(path.read_text(encoding='utf-8')))


def subset(actual, expected):
    if isinstance(expected, dict):
        for key, value in expected.items():
            assert key in actual
            subset(actual[key], value)
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected):
            subset(a, b)
    else:
        assert actual == expected


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_contract_examples(make_client, case):
    c = make_client()
    saved = {}
    def resolve(value):
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v) for v in value]
        if not isinstance(value, str):
            return value
        def lookup(path):
            out = saved
            for part in path.split('.'):
                out = out[int(part)] if isinstance(out, list) else out[part]
            return out
        full = re.fullmatch(r'\{\{([^{}]+)\}\}', value)
        if full:
            return lookup(full[1])
        return re.sub(r'\{\{([^{}]+)\}\}', lambda m: str(lookup(m[1])), value)
    for step in case.get('steps', [case]):
        if step.get('user'):
            login(c, step['user'])
        kw = {}
        if 'json' in step:
            kw['json'] = resolve(step['json'])
        if 'form' in step:
            kw['data'] = resolve(step['form'])
            kw['files'] = {'file': (step['file']['name'], step['file']['content'].encode())}
        r = c.request(step['method'], resolve(step['path']), **kw)
        assert r.status_code == step['status'], r.text
        if 'text' in step:
            assert r.text == step['text']
            continue
        body = r.json()
        if 'capture' in step:
            saved[step['capture']] = body
        if 'keys' in step:
            assert set(body) == set(step['keys'])
        subset(body, resolve(step['expect']))



def test_conventions_match_runtime():
    from haiknow_sdk.resources import ERROR_STATUS
    spec = json.loads((ROOT / 'tests/fixtures/v1/conventions.json').read_text(encoding='utf-8'))
    assert {code.upper(): status for code, status in ERROR_STATUS.items()} == spec['errors']

    def statuses(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k == 'status' and isinstance(v, str):
                    yield v
                yield from statuses(v)
        elif isinstance(value, list):
            for v in value:
                yield from statuses(v)
    assert set(spec['states']) <= set(statuses(CASES))
