"""SDK 版本不兼容只影响声明它的应用。"""
import json
import shutil

import pytest

from conftest import ROOT
from test_platform import login


@pytest.mark.parametrize('sdk', ['2', 2, '1.0', '', None, True])
def test_unsupported_sdk_is_unavailable(make_client, tmp_path, sdk):
    apps = tmp_path / 'apps'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', apps / 'sample-app')
    bad = apps / 'future-app'
    (bad / 'api').mkdir(parents=True)
    manifest = json.loads((apps / 'sample-app/app.json').read_text())
    manifest.update(id='future-app', sdk=sdk)
    (bad / 'app.json').write_text(json.dumps(manifest))
    # 不兼容的代码根本不应导入。
    (bad / 'api/router.py').write_text("raise RuntimeError('不应运行')\n")
    c = make_client(apps)
    assert c.get('/api/health').json()['ok'] is True
    login(c, 'sampleadmin')
    entry = next(a for a in c.get('/api/apps').json()['apps'] if a['id'] == 'future-app')
    assert entry['available'] is False
    assert 'SDK' in entry['error'] and '不应运行' not in entry['error']
    assert c.get('/api/apps/sample-app/records').status_code == 200


def test_sdk_one_and_legacy_manifest():
    from haiknow_core import manifest
    from haiknow_sdk import SDK_VERSION

    m = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    legacy = {key: value for key, value in m.items() if key != 'sdk'}
    assert SDK_VERSION == '1.0.0'
    assert m['sdk'] == '1'
    assert manifest.validate(m) == []
    assert manifest.validate(legacy) == []
    assert manifest.sdk_error(legacy) == ''
    assert manifest.sdk_error({**legacy, 'sdk': '2'}) != ''


@pytest.mark.parametrize('value', [[], None, 'wrong', {'defaultRoles': ['bad']}, {'defaultRoles': {'sampleoperator': 2}}, {'actions': 2}])
def test_malformed_manifest_does_not_prevent_startup(make_client, tmp_path, value):
    apps = tmp_path / 'apps'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', apps / 'sample-app')
    bad = apps / 'broken-app'
    bad.mkdir()
    m = json.loads((apps / 'sample-app/app.json').read_text())
    manifest = {**m, 'id': 'broken-app', **value} if isinstance(value, dict) else value
    (bad / 'app.json').write_text(json.dumps(manifest))
    c = make_client(apps)
    assert c.get('/api/health').json()['broken'] == 1
    login(c, 'sampleoperator')
    assert c.get('/api/apps/sample-app/records').status_code == 200
