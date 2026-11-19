"""DataError 契约：应用自定义码默认 400、平台码映射不变、details 原样进信封（Refs #51）。"""
import json

from haiknow_sdk.resources import ERROR_STATUS, DataError
from test_platform import login

from conftest import ROOT


def test_custom_code_defaults_to_400_with_envelope():
    error = DataError('loan_period_invalid', '借期需在 1–30 天')
    assert error.code == 'loan_period_invalid'
    assert error.status == 400
    assert str(error) == '借期需在 1–30 天'
    assert error.error == {
        'code': 'loan_period_invalid',
        'message': '借期需在 1–30 天',
        'retryable': False,
    }


def test_details_are_passed_through_unchanged():
    error = DataError('loan_period_invalid', '借期需在 1–30 天', status='recheck', fields=['period'])
    assert error.status == 400
    assert error.error == {
        'code': 'loan_period_invalid',
        'message': '借期需在 1–30 天',
        'retryable': False,
        'status': 'recheck',
        'fields': ['period'],
    }


def test_platform_codes_keep_their_status():
    for code, status in ERROR_STATUS.items():
        assert DataError(code, '平台错误').status == status


ROUTER = '''
from fastapi import APIRouter

from haiknow_sdk import DataError

router = APIRouter()


@router.post('/custom')
def custom():
    raise DataError('loan_period_invalid', '借期需在 1–30 天')


@router.post('/custom-detail')
def custom_detail():
    raise DataError('loan_period_invalid', '借期需在 1–30 天', status='recheck')


@router.post('/platform')
def platform():
    raise DataError('not_found', '记录不存在')
'''


def test_app_router_returns_real_http_envelope(make_client, tmp_path):
    apps = tmp_path / 'apps'
    app = apps / 'sdk-dataerror'
    (app / 'api').mkdir(parents=True)
    manifest = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text(encoding='utf-8'))
    (app / 'app.json').write_text(json.dumps({**manifest, 'id': 'sdk-dataerror'}), encoding='utf-8')
    (app / 'api/router.py').write_text(ROUTER, encoding='utf-8')

    client = make_client(apps)
    login(client, 'sampleoperator')
    base = '/api/apps/sdk-dataerror'

    custom = client.post(base + '/custom')
    assert custom.status_code == 400
    assert custom.json() == {
        'error': {
            'code': 'LOAN_PERIOD_INVALID',
            'message': '借期需在 1–30 天',
            'retryable': False,
        }
    }

    detailed = client.post(base + '/custom-detail')
    assert detailed.status_code == 400
    assert detailed.json()['error']['status'] == 'recheck'

    platform = client.post(base + '/platform')
    assert platform.status_code == 404
    assert platform.json()['error']['code'] == 'NOT_FOUND'