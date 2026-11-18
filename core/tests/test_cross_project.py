"""跨项目主体授权端到端测试；所有主体编号与原件内容均为虚构样例。"""
import base64
import json
import shutil

from conftest import ROOT
from test_platform import login


APP_ID = 'supplier-records'
BASE = f'/api/v1/apps/{APP_ID}/records'


def app_tree(tmp_path):
    apps = tmp_path / 'apps'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', apps / 'sample-app')
    app = apps / APP_ID
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', app)
    (app / 'api').mkdir(parents=True, exist_ok=True)
    manifest = json.loads((app / 'app.json').read_text(encoding='utf-8'))
    manifest.update(
        id=APP_ID,
        name='虚构供应商资料',
        crossProject={'subjectField': 'supplierCode'},
        defaultRoles={'sampleoperator': ['view', 'operate'], 'samplereviewer': ['view', 'approve']},
    )
    (app / 'app.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    (app / 'api/router.py').write_text(
        """import base64
from fastapi import APIRouter, Depends
from haiknow_sdk import app_context

router = APIRouter()

@router.get('/preview/records')
def preview_records(subject: str, ctx=Depends(app_context)):
    return ctx.preview.cross_project.records(subject)

@router.get('/preview/records/{record_id}')
def preview_record(record_id: str, version: int | None = None, ctx=Depends(app_context)):
    return ctx.preview.cross_project.get(record_id, version)

@router.get('/preview/files/{file_id}')
def preview_file(file_id: str, ctx=Depends(app_context)):
    return {'content': base64.b64encode(ctx.preview.cross_project.read_file(file_id)).decode('ascii')}
""",
        encoding='utf-8',
    )
    return apps


def add_record(client, project, subject, kind, content):
    file = client.post('/api/v1/files', data={
        'app': APP_ID, 'project': project, 'purpose': '虚构凭证',
    }, files={'file': (f'{kind}.txt', content.encode())})
    assert file.status_code == 201, file.text
    result = client.post(BASE, json={
        'project': project, 'type': kind,
        'data': {'supplierCode': subject, 'summary': f'{kind} 样例'},
        'files': [file.json()['fileId']],
    })
    assert result.status_code == 201, result.text
    return result.json(), file.json()['fileId']


def test_cross_project_subject_records_versions_files_revocation_and_audit(make_client, tmp_path):
    client = make_client(app_tree(tmp_path))
    login(client, 'sampleadmin')
    project_a, project_b = 'sample-project', 'limited-project'
    in_a, file_a = add_record(client, project_a, 'SUP-SAMPLE-01', 'supplier', 'A 原件样例')
    member_update = client.put(f'/api/admin/projects/{project_b}/members', json={
        'members': ['sampleadmin', 'sampleoperator', 'samplereviewer'],
    })
    assert member_update.status_code == 200, member_update.text
    login(client, 'sampleoperator')
    in_b, file_b = add_record(client, project_b, 'SUP-SAMPLE-01', 'quote', 'B 业务资料原件样例')
    review = client.post('/api/v1/reviews', json={
        'appId': APP_ID, 'recordId': in_b['id'], 'version': 1, 'assignee': 'samplereviewer',
    })
    assert review.status_code == 201, review.text
    login(client, 'samplereviewer')
    decided = client.post(f'/api/v1/reviews/{review.json()["id"]}/decisions', json={
        'version': 1, 'decision': 'confirm',
    })
    assert decided.status_code == 200, decided.text
    login(client, 'sampleadmin')
    member_update = client.put(f'/api/admin/projects/{project_b}/members', json={'members': ['sampleadmin']})
    assert member_update.status_code == 200, member_update.text
    other, _ = add_record(client, project_b, 'SUP-SAMPLE-02', 'quote', 'T 主体原件样例')
    revision = client.put(f'{BASE}/{in_b["id"]}', json={
        'baseVersion': 1, 'data': {'supplierCode': 'SUP-SAMPLE-01', 'summary': '业务资料修订样例'},
    })
    assert revision.status_code == 200 and revision.json()['version'] == 2
    linked = client.post(BASE, json={
        'project': project_a, 'type': 'reference',
        'data': {'supplierCode': 'SUP-LOCAL-REF', 'summary': '跨项目引用样例'},
        'refs': [{'appId': APP_ID, 'recordId': in_b['id'], 'version': 1, 'fileId': file_b}],
    })
    assert linked.status_code == 201, linked.text

    login(client, 'sampleoperator')
    for url in [
        f'{BASE}/{in_b["id"]}', f'{BASE}/{in_b["id"]}/versions/1',
        f'/api/v1/files/{file_b}', f'/api/v1/files/{file_b}/content',
    ]:
        denied = client.get(url)
        assert denied.status_code == 404 and denied.json()['error']['code'] == 'not_found'
    local = client.get(f'/api/apps/{APP_ID}/preview/records', params={'subject': 'SUP-SAMPLE-01'})
    assert local.status_code == 200 and [row['id'] for row in local.json()['items']] == [in_a['id']]

    login(client, 'sampleadmin')
    grant = client.post('/api/admin/cross-project-grants', json={
        'appId': APP_ID, 'subjectField': 'supplierCode', 'subjectValue': 'SUP-SAMPLE-01',
        'principalType': 'role', 'principalId': 'sampleoperator',
    })
    assert grant.status_code == 201, grant.text
    grant_id = grant.json()['id']

    login(client, 'sampleoperator')
    rows = client.get(f'/api/apps/{APP_ID}/preview/records', params={'subject': 'SUP-SAMPLE-01'}).json()['items']
    assert {row['id'] for row in rows} == {in_a['id'], in_b['id']}
    assert {row['sourceProject'] for row in rows} == {project_a, project_b}
    assert other['id'] not in {row['id'] for row in rows}
    assert client.get(f'{BASE}/{in_b["id"]}').json()['id'] == in_b['id']
    assert client.get(f'/api/apps/{APP_ID}/preview/records/{in_b["id"]}', params={'version': 1}).json()['sourceProject'] == project_b
    assert client.get(f'{BASE}/{in_b["id"]}/versions/1').json()['data']['summary'] == 'quote 样例'
    assert client.get(f'/api/v1/files/{file_b}').json()['project'] == project_b
    assert client.get(f'/api/v1/files/{file_b}/content').content == 'B 业务资料原件样例'.encode()
    python_file = client.get(f'/api/apps/{APP_ID}/preview/files/{file_b}')
    assert base64.b64decode(python_file.json()['content']) == 'B 业务资料原件样例'.encode()
    assert client.put(f'{BASE}/{in_b["id"]}', json={
        'baseVersion': 2, 'data': {'supplierCode': 'SUP-SAMPLE-01'},
    }).status_code == 404

    login(client, 'sampleadmin')
    assert client.delete(f'/api/admin/cross-project-grants/{grant_id}').json() == {'ok': True, 'revoked': True}
    grant_rows = client.get('/api/admin/cross-project-grants').json()['grants']
    revoked = next(row for row in grant_rows if row['id'] == grant_id)
    assert revoked['revokedBy'] == 'sampleadmin' and revoked['revokedAt'] is not None

    login(client, 'sampleoperator')
    remaining = client.get(f'/api/apps/{APP_ID}/preview/records', params={'subject': 'SUP-SAMPLE-01'}).json()['items']
    assert [row['id'] for row in remaining] == [in_a['id']]
    assert client.get(f'{BASE}/{in_b["id"]}').status_code == 404
    assert client.get(f'/api/v1/files/{file_b}/content').status_code == 404

    audit = client.app.state.platform.store.audit_list('platform')
    actions = [row['action'] for row in audit]
    assert 'cross_project.grant.create' in actions and 'cross_project.grant.revoke' in actions
    access = client.app.state.platform.store.audit_list(APP_ID)
    assert any(row['action'] == 'v1.cross_project.read' and row['detail']['resourceId'] == in_b['id'] for row in access)
    assert any(row['action'] == 'v1.cross_project.read' and row['detail']['resourceId'] == file_b for row in access)


def test_cross_project_grants_validate_manifest_and_admin(make_client, tmp_path):
    client = make_client(app_tree(tmp_path))
    login(client, 'sampleoperator')
    denied = client.post('/api/admin/cross-project-grants', json={
        'appId': APP_ID, 'subjectField': 'supplierCode', 'subjectValue': None,
        'principalType': 'role', 'principalId': 'sampleoperator',
    })
    assert denied.status_code == 403
    login(client, 'sampleadmin')
    invalid = client.post('/api/admin/cross-project-grants', json={
        'appId': APP_ID, 'subjectField': 'unknownField', 'subjectValue': None,
        'principalType': 'role', 'principalId': 'sampleoperator',
    })
    assert invalid.status_code == 422 and invalid.json()['error']['code'] == 'invalid_request'


def test_user_grant_scopes_subject_and_revoke_is_immediate(make_client, tmp_path):
    client = make_client(app_tree(tmp_path))
    login(client, 'sampleadmin')
    record, file_id = add_record(client, 'limited-project', 'SUP-SAMPLE-03', 'evidence', '用户授权原件样例')
    grant = client.post('/api/admin/cross-project-grants', json={
        'appId': APP_ID, 'subjectField': 'supplierCode', 'subjectValue': 'SUP-SAMPLE-03',
        'principalType': 'user', 'principalId': 'sampleoperator',
    })
    assert grant.status_code == 201
    login(client, 'sampleoperator')
    assert client.get(f'{BASE}/{record["id"]}').status_code == 200
    assert client.get(f'/api/v1/files/{file_id}/content').content == '用户授权原件样例'.encode()
    login(client, 'sampleadmin')
    assert client.delete(f'/api/admin/cross-project-grants/{grant.json()["id"]}').status_code == 200
    login(client, 'sampleoperator')
    denied = client.get(f'{BASE}/{record["id"]}')
    assert denied.status_code == 404 and denied.json()['error']['code'] == 'not_found'
    assert client.get(f'/api/v1/files/{file_id}/content').status_code == 404


def test_deleting_and_recreating_role_does_not_restore_old_cross_project_grant(make_client, tmp_path):
    client = make_client(app_tree(tmp_path))
    login(client, 'sampleadmin')
    record, _ = add_record(client, 'limited-project', 'SUP-ROLE-01', 'supplier', '角色生命周期样例')
    role = client.post('/api/admin/roles', json={'id': 'supplier-reader', 'name': '供应商只读人'})
    assert role.status_code == 201, role.text
    grant = client.post('/api/admin/cross-project-grants', json={
        'appId': APP_ID, 'subjectField': 'supplierCode', 'subjectValue': 'SUP-ROLE-01',
        'principalType': 'role', 'principalId': 'supplier-reader',
    })
    assert grant.status_code == 201, grant.text
    grant_id = grant.json()['id']

    assert client.delete('/api/admin/roles/supplier-reader').status_code == 200
    assert client.post('/api/admin/roles', json={
        'id': 'supplier-reader', 'name': '重新建立的同编号角色',
    }).status_code == 201
    updated = client.patch('/api/admin/users/sampleoperator', json={'roles': ['sampleoperator', 'supplier-reader']})
    assert updated.status_code == 200, updated.text
    revoked = next(row for row in client.get('/api/admin/cross-project-grants').json()['grants'] if row['id'] == grant_id)
    assert revoked['revokedBy'] == 'sampleadmin' and revoked['revokedAt'] is not None

    login(client, 'sampleoperator')
    denied = client.get(f'{BASE}/{record["id"]}')
    assert denied.status_code == 404 and denied.json()['error']['code'] == 'not_found'


def test_another_apps_subject_grant_does_not_expose_original_app_file(make_client, tmp_path):
    apps = app_tree(tmp_path)
    other_app_id = 'other-supplier-records'
    other_app = apps / other_app_id
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', other_app)
    manifest = json.loads((other_app / 'app.json').read_text(encoding='utf-8'))
    manifest.update(
        id=other_app_id,
        name='另一应用供应商记录',
        crossProject={'subjectField': 'supplierCode'},
        defaultRoles={'sampleoperator': ['view', 'operate']},
    )
    (other_app / 'app.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')

    client = make_client(apps)
    login(client, 'sampleadmin')
    assert client.put('/api/admin/projects/limited-project/members', json={
        'members': ['sampleadmin', 'sampleoperator', 'samplereviewer'],
    }).status_code == 200
    login(client, 'sampleoperator')
    source, file_id = add_record(client, 'limited-project', 'SUP-SOURCE-01', 'supplier', '原应用原件样例')
    review = client.post('/api/v1/reviews', json={
        'appId': APP_ID, 'recordId': source['id'], 'version': 1, 'assignee': 'samplereviewer',
    })
    assert review.status_code == 201, review.text
    login(client, 'samplereviewer')
    assert client.post(f'/api/v1/reviews/{review.json()["id"]}/decisions', json={
        'version': 1, 'decision': 'confirm',
    }).status_code == 200
    login(client, 'sampleadmin')
    assert client.put('/api/admin/projects/limited-project/members', json={'members': ['sampleadmin']}).status_code == 200
    linked = client.post(f'/api/v1/apps/{other_app_id}/records', json={
        'project': 'limited-project', 'type': 'reference',
        'data': {'supplierCode': 'SUP-OTHER-01', 'summary': '另一应用引用样例'},
        'refs': [{'appId': APP_ID, 'recordId': source['id'], 'version': 1, 'fileId': file_id}],
    })
    assert linked.status_code == 201, linked.text
    grant = client.post('/api/admin/cross-project-grants', json={
        'appId': other_app_id, 'subjectField': 'supplierCode', 'subjectValue': 'SUP-OTHER-01',
        'principalType': 'role', 'principalId': 'sampleoperator',
    })
    assert grant.status_code == 201, grant.text

    login(client, 'sampleoperator')
    denied = client.get(f'/api/v1/files/{file_id}/content')
    assert denied.status_code == 404 and denied.json()['error']['code'] == 'not_found'
