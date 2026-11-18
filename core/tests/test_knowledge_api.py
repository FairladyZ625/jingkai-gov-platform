"""知识库（CAP-04）验收：上传入库、版本与替代、引用反查、检索与权限。"""
import json

from test_platform import login

BASE = '/api/v1/knowledge'
SAMPLE = '合成检验依据：本文件仅用于测试。'.encode()


def upload(c, *, title='检验依据（测试）', category='01-制度标准通知', visibility='internal',
           roles='', departments='', tags='检验,标准', note='首次入库', text='', project='sample-project',
           scope='project',
           app='sample-app', body=SAMPLE):
    return c.post(f'{BASE}/entries', data={
        'title': title, 'category': category, 'sourceApp': app, 'project': project,
        'scope': scope, 'visibility': visibility, 'roles': roles, 'departments': departments, 'tags': tags,
        'note': note, 'text': text, 'purpose': '知识库',
    }, files={'file': ('依据.txt', body)})


def publish(c, entry_id, version):
    return c.post(f'{BASE}/entries/{entry_id}/publish', json={'version': version})


def test_upload_registers_entry_with_category_version_and_file(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    r = upload(c, text='合成检验依据正文，可被关键词检索')
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry['category'] == '01-制度标准通知'
    assert entry['tags'] == ['检验', '标准'] and entry['visibility'] == 'internal'
    assert entry['status'] == 'unreviewed' and entry['publishedVersion'] is None
    assert entry['latest']['version'] == 1 and entry['latest']['fileId']
    assert len(entry['latest']['sha256']) == 64 and entry['latest']['size'] > 0
    first_file = entry['latest']['fileId']

    # 未审核条目默认不出现在检索里，维护人可用 includeUnpublished 查看。
    assert c.get(f'{BASE}/entries').json()['items'] == []
    listed = c.get(f'{BASE}/entries', params={'includeUnpublished': True}).json()
    assert [item['id'] for item in listed['items']] == [entry['id']]

    # 换版追加新原件，旧版本仍可取，原件不被覆盖。
    r = c.post(f'{BASE}/entries/{entry["id"]}/versions', data={'note': '按 2026 版替换'},
               files={'file': ('依据-v2.txt', SAMPLE + b'v2')})
    assert r.status_code == 201, r.text
    updated = r.json()
    assert updated['latestVersion'] == 2 and updated['latest']['version'] == 2
    assert updated['latest']['fileId'] != first_file
    changed_project = c.post(f'{BASE}/entries/{entry["id"]}/versions', data={
        'note': '不得迁移项目', 'project': 'limited-project',
    }, files={'file': ('其他项目.txt', b'other-project')})
    assert changed_project.status_code == 422
    old = c.get(f'{BASE}/entries/{entry["id"]}/versions/1').json()
    assert old['fileId'] == first_file
    assert old['effective'] is False


def test_publish_supersedes_previous_version_and_keeps_it_readable(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    entry = upload(c).json()
    entry_id = entry['id']

    # 办理员没有发布权限
    assert publish(c, entry_id, 1).status_code == 403

    login(c, 'samplereviewer')
    first = publish(c, entry_id, 1).json()
    assert first['status'] == 'published' and first['publishedVersion'] == 1
    assert first['versions'][0]['status'] == 'published'

    login(c, 'sampleoperator')
    r = c.post(f'{BASE}/entries/{entry_id}/versions', data={'note': '第二版'}, files={'file': ('v2.txt', SAMPLE + b'2')})
    assert r.status_code == 201, r.text
    submitted = c.post(f'{BASE}/entries/{entry_id}/submit', json={'version': 2})
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()['status'] == 'pending'

    # 待核版本不改变正式依据：默认检索仍给出已发布 v1，最新版本标记为待核。
    items = c.get(f'{BASE}/entries').json()['items']
    assert [item['id'] for item in items] == [entry_id]
    assert items[0]['publishedVersion'] == 1 and items[0]['effective']['version'] == 1
    assert items[0]['latest']['version'] == 2 and items[0]['latest']['status'] == 'pending'
    assert [item['id'] for item in c.get(f'{BASE}/entries', params={'status': 'pending'}).json()['items']] == [entry_id]

    # 待核正文不能当依据读：只读账号 403，维护人可读。
    login(c, 'sampleobserver')
    assert c.get(f'{BASE}/entries/{entry_id}/versions/2/content').status_code == 403
    assert c.get(f'{BASE}/entries/{entry_id}/versions/1/content').status_code == 200
    login(c, 'sampleoperator')
    assert c.get(f'{BASE}/entries/{entry_id}/versions/2/content').status_code == 200

    # 发布 v2 后 v1 标记已替代，但仍可读取，只是不再有效。
    login(c, 'samplereviewer')
    second = publish(c, entry_id, 2).json()
    assert second['publishedVersion'] == 2
    statuses = {item['version']: item['status'] for item in second['versions']}
    assert statuses == {1: 'superseded', 2: 'published'}
    login(c, 'sampleobserver')
    old = c.get(f'{BASE}/entries/{entry_id}/versions/1').json()
    assert old['status'] == 'superseded' and old['effective'] is False
    assert c.get(f'{BASE}/entries/{entry_id}/versions/1/content').status_code == 200


def test_search_filters_permissions_and_validation(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    public = upload(c, title='公开通知', category='01-制度标准通知', visibility='public',
                    tags='通知', text='全员可读的制度通知').json()
    internal = upload(c, title='内部记录', category='05-制造质量交付', visibility='internal',
                      tags='质保', text='来源应用可见的质保记录').json()
    restricted = upload(c, title='受限简历', category='07-人员行政培训', visibility='restricted',
                        roles='samplereviewer', tags='简历', text='仅审核员可见').json()
    login(c, 'samplereviewer')
    for entry in (public, internal, restricted):
        assert publish(c, entry['id'], 1).status_code == 200

    # 没有项目成员身份的账号看不到默认项目范围条目，即使 visibility=public。
    login(c, 'sampleoutsider')
    assert c.get(f'{BASE}/entries').json()['items'] == []
    assert c.get(f'{BASE}/entries/{public["id"]}').status_code == 403
    assert c.get(f'{BASE}/entries/{restricted["id"]}').status_code == 403
    assert c.get(f'{BASE}/entries/{restricted["id"]}/versions/1/content').status_code == 403

    login(c, 'sampleobserver')
    visible = {item['id'] for item in c.get(f'{BASE}/entries').json()['items']}
    assert visible == {public['id'], internal['id']}
    assert c.get(f'{BASE}/entries/{restricted["id"]}/versions/1/content').status_code == 403

    login(c, 'samplereviewer')
    assert {item['id'] for item in c.get(f'{BASE}/entries').json()['items']} == {
        public['id'], internal['id'], restricted['id']}
    by_keyword = c.get(f'{BASE}/entries', params={'q': '质保'}).json()['items']
    assert [item['id'] for item in by_keyword] == [internal['id']]
    assert [item['id'] for item in c.get(f'{BASE}/entries', params={'category': '07-人员行政培训'}).json()['items']] == [restricted['id']]
    assert [item['id'] for item in c.get(f'{BASE}/entries', params={'app': 'sample-app'}).json()['items']] != []
    assert c.get(f'{BASE}/entries', params={'category': '09-不存在'}).status_code == 422
    assert c.get(f'{BASE}/entries', params={'status': 'superseded'}).status_code == 422
    assert c.get(f'{BASE}/entries', params={'limit': 0}).status_code == 422
    assert c.get(f'{BASE}/categories').json()['items'][0] == '01-制度标准通知'
    assert len(c.get(f'{BASE}/categories').json()['items']) == 8


def test_references_link_records_to_file_versions_both_directions(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    file_doc = c.post('/api/v1/files', data={'app': 'sample-app', 'project': 'sample-project', 'purpose': '检验'},
                      files={'file': ('现场照片.jpg', b'fake-jpeg')}).json()
    entry = c.post(f'{BASE}/entries', data={
        'title': '现场照片（测试）', 'category': '05-制造质量交付', 'sourceApp': 'sample-app',
        'visibility': 'internal', 'tags': '照片', 'fileId': file_doc['fileId'],
    }).json()
    assert entry['latest']['fileId'] == file_doc['fileId']
    login(c, 'samplereviewer')
    assert publish(c, entry['id'], 1).status_code == 200

    login(c, 'sampleoperator')
    record = c.post('/api/v1/apps/sample-app/records', json={
        'project': 'sample-project', 'type': 'inspection',
        'data': {'productNo': 'DEMO-P-001'}, 'files': [file_doc['fileId']],
    }).json()

    refs = c.get(f'{BASE}/entries/{entry["id"]}/references').json()['items']
    assert {(item['recordId'], item['recordVersion'], item['entryVersion'], item['fileId']) for item in refs} == {
        (record['id'], 1, 1, file_doc['fileId'])}

    files = c.get(f'{BASE}/records/sample-app/{record["id"]}/versions/1/files').json()['items']
    assert [(item['entryId'], item['entryVersion'], item['fileId']) for item in files] == [
        (entry['id'], 1, file_doc['fileId'])]

    # 记录改版后旧版本仍能解释当时引用的文件版本。
    login(c, 'sampleoperator')
    r = c.put(f'/api/v1/apps/sample-app/records/{record["id"]}', json={
        'baseVersion': 1, 'project': 'sample-project', 'type': 'inspection',
        'data': {'productNo': 'DEMO-P-001'}, 'files': [],
    })
    assert r.status_code == 200, r.text
    assert c.get(f'{BASE}/records/sample-app/{record["id"]}/versions/1/files').json()['items'][0]['entryVersion'] == 1

    # 条目换版不影响旧记录指向的版本。
    login(c, 'samplereviewer')
    new_file = c.post('/api/v1/files', data={'app': 'sample-app', 'project': 'sample-project', 'purpose': '检验'},
                      files={'file': ('现场照片-v2.jpg', b'fake-jpeg-2')}).json()
    assert c.post(f'{BASE}/entries/{entry["id"]}/versions', data={'note': '换版'}, files={
        'file': ('现场照片-v2.jpg', b'fake-jpeg-2')}).status_code == 201
    publish(c, entry['id'], 2)
    login(c, 'sampleoperator')
    files = c.get(f'{BASE}/records/sample-app/{record["id"]}/versions/1/files').json()['items']
    assert [(item['entryVersion'], item['fileStatus']) for item in files] == [(1, 'superseded')]


def test_restricted_file_is_blocked_on_legacy_v1_entry_until_permitted(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    file_doc = c.post('/api/v1/files', data={'app': 'sample-app', 'project': 'sample-project', 'purpose': '简历'},
                      files={'file': ('简历.txt', '合成简历正文'.encode())}).json()
    fid = file_doc['fileId']
    # 未登记知识库时旧入口行为不变：项目内可见者都能读。
    login(c, 'sampleobserver')
    assert c.get(f'/api/v1/files/{fid}').status_code == 200
    assert c.get(f'/api/v1/files/{fid}/content').status_code == 200

    login(c, 'sampleoperator')
    entry = c.post(f'{BASE}/entries', data={
        'title': '受限简历（测试）', 'category': '07-人员行政培训', 'sourceApp': 'sample-app',
        'visibility': 'restricted', 'roles': 'samplereviewer', 'fileId': fid,
    }).json()
    login(c, 'samplereviewer')
    assert publish(c, entry['id'], 1).status_code == 200

    # 已登记为受限：旧 v1 文件入口与知识库原件入口都拒绝无权限者。
    login(c, 'sampleobserver')
    assert c.get(f'/api/v1/files/{fid}').status_code == 403
    assert c.get(f'/api/v1/files/{fid}/content').status_code == 403
    assert c.get(f'{BASE}/entries/{entry["id"]}/versions/1/content').status_code == 403
    login(c, 'samplereviewer')
    assert c.get(f'/api/v1/files/{fid}').status_code == 200
    assert c.get(f'{BASE}/entries/{entry["id"]}/versions/1/content').status_code == 200


def test_project_scoped_entry_blocks_matching_roles_outside_project(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    assert 'limited-project' not in c.app.state.platform.directory.project_ids('samplereviewer')

    outcomes = {}
    for visibility, roles in [('internal', ''), ('restricted', 'samplereviewer')]:
        created = c.post(f'{BASE}/entries', data={
            'title': f'项目范围 {visibility}（合成）', 'category': '05-制造质量交付',
            'sourceApp': 'sample-app', 'project': 'sample-project',
            'visibility': visibility, 'roles': roles, 'text': f'CAP97-{visibility}',
            'purpose': '合成依据',
        }, files={'file': ('项目依据.txt', '虚构项目资料'.encode())})
        assert created.status_code == 201, created.text
        entry = created.json()
        entry_id = entry['id']
        # 把已合法创建的虚构样本移入另一个项目，模拟项目成员配置与存量数据。
        store = c.app.state.platform.store
        with store._lock, store._db:
            row = store._db.execute('select document from kb_entries where id=?', (entry_id,)).fetchone()
            entry_doc = json.loads(row[0])
            entry_doc['project'] = 'limited-project'
            store._db.execute('update kb_entries set document=? where id=?',
                              (json.dumps(entry_doc, ensure_ascii=False), entry_id))
            file_row = store._db.execute('select document from v1_files where id=?',
                                         (entry['latest']['fileId'],)).fetchone()
            file_doc = json.loads(file_row[0])
            file_doc['project'] = 'limited-project'
            store._db.execute('update v1_files set project=?,document=? where id=?',
                              ('limited-project', json.dumps(file_doc, ensure_ascii=False), entry['latest']['fileId']))
        login(c, 'sampleadmin')
        saved_record = c.post('/api/v1/apps/sample-app/records', json={
            'project': 'limited-project', 'type': 'inspection',
            'data': {'sample': 'DEMO-97'}, 'files': [entry['latest']['fileId']],
        })
        assert saved_record.status_code == 201, saved_record.text
        record = saved_record.json()
        for phase in ('unpublished', 'published'):
            login(c, 'samplereviewer')
            listing = c.get(f'{BASE}/entries', params={
                'includeUnpublished': phase == 'unpublished', 'q': f'CAP97-{visibility}',
            }).json()['items']
            outcomes[f'{visibility}/{phase}/search'] = any(item['id'] == entry_id for item in listing)
            outcomes[f'{visibility}/{phase}/detail'] = c.get(f'{BASE}/entries/{entry_id}').status_code
            outcomes[f'{visibility}/{phase}/version'] = c.get(f'{BASE}/entries/{entry_id}/versions/1').status_code
            outcomes[f'{visibility}/{phase}/content'] = c.get(
                f'{BASE}/entries/{entry_id}/versions/1/content').status_code
            outcomes[f'{visibility}/{phase}/references'] = c.get(
                f'{BASE}/entries/{entry_id}/references').status_code
            outcomes[f'{visibility}/{phase}/file-meta'] = c.get(
                f'/api/v1/files/{entry["latest"]["fileId"]}').status_code
            outcomes[f'{visibility}/{phase}/file-content'] = c.get(
                f'/api/v1/files/{entry["latest"]["fileId"]}/content').status_code
            outcomes[f'{visibility}/{phase}/record-files'] = c.get(
                f'{BASE}/records/sample-app/{record["id"]}/versions/1/files').status_code
            if phase == 'unpublished':
                login(c, 'sampleadmin')
                assert publish(c, entry_id, 1).status_code == 200

    expected = {
        f'{visibility}/{phase}/{path}': value
        for visibility in ('internal', 'restricted')
        for phase in ('unpublished', 'published')
        for path, value in (
            ('search', False), ('detail', 403), ('version', 403), ('content', 403),
            ('references', 403), ('file-meta', 404), ('file-content', 404), ('record-files', 404),
        )
    }
    assert outcomes == expected, f'观察到的修前/修后路径状态：{outcomes}'


def test_every_write_is_audited_and_metadata_change_needs_approve(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    entry = upload(c).json()
    entry_id = entry['id']
    assert c.post(f'{BASE}/entries/{entry_id}/versions', data={'note': '换版'},
                  files={'file': ('v2.txt', SAMPLE + b'2')}).status_code == 201
    assert c.post(f'{BASE}/entries/{entry_id}/submit', json={'version': 2}).status_code == 200
    # 改可见范围需要审核权限
    assert c.patch(f'{BASE}/entries/{entry_id}', json={'visibility': 'public'}).status_code == 403
    login(c, 'samplereviewer')
    assert publish(c, entry_id, 2).status_code == 200
    assert c.patch(f'{BASE}/entries/{entry_id}', json={'visibility': 'public', 'tags': ['检验']}).status_code == 200

    audit = c.app.state.platform.store.audit_list(limit=100)
    actions = [item['action'] for item in audit]
    assert {'knowledge.entry.create', 'knowledge.entry.version', 'knowledge.entry.submit',
            'knowledge.entry.publish', 'knowledge.entry.update'} <= set(actions)
    assert '虚构简历' not in json.dumps(audit, ensure_ascii=False)


def test_project_membership_controls_maintenance_and_company_share(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    project_entry = upload(c, title='项目成员权限（合成）', text='项目内正式依据').json()
    shared_entry = upload(c, title='公司共享权限（合成）', text='公司共享正式依据').json()

    assert upload(c, title='越权公司共享（合成）', scope='company').status_code == 403
    denied_share = c.patch(f'{BASE}/entries/{shared_entry["id"]}', json={'scope': 'company'})
    assert denied_share.status_code == 403
    assert c.post(f'{BASE}/entries/{project_entry["id"]}/versions', data={
        'project': 'limited-project', 'note': '不得扩大范围',
    }, files={'file': ('错误项目.txt', b'other-project')}).status_code == 422

    login(c, 'sampleobserver')
    assert c.get(f'{BASE}/entries/{project_entry["id"]}').status_code == 403
    assert c.get(f'{BASE}/entries/{project_entry["id"]}/versions/1/content').status_code == 403

    login(c, 'samplereviewer')
    assert publish(c, project_entry['id'], 1).status_code == 200
    shared_created = upload(c, title='通过审核共享（合成）', scope='company')
    assert shared_created.status_code == 201, shared_created.text
    assert shared_created.json()['scope'] == 'company'
    assert c.patch(f'{BASE}/entries/{shared_entry["id"]}', json={'scope': 'company'}).status_code == 200
    assert publish(c, shared_entry['id'], 1).status_code == 200

    login(c, 'sampleobserver')
    assert c.get(f'{BASE}/entries/{project_entry["id"]}').status_code == 200
    assert c.get(f'{BASE}/entries/{project_entry["id"]}/versions/1/content').status_code == 200
    assert c.post(f'{BASE}/entries/{project_entry["id"]}/versions', data={'note': '只读角色'},
                  files={'file': ('只读.txt', b'read-only')}).status_code == 403

    login(c, 'sampleadmin')
    member_update = c.put('/api/admin/projects/sample-project/members', json={
        'members': ['sampleadmin', 'sampleoperator', 'sampleobserver'],
    })
    assert member_update.status_code == 200, member_update.text
    login(c, 'samplereviewer')
    assert c.get(f'{BASE}/entries/{project_entry["id"]}').status_code == 403
    assert c.get(f'{BASE}/entries/{project_entry["id"]}/versions/1/content').status_code == 403
    assert c.post(f'{BASE}/entries/{project_entry["id"]}/publish', json={'version': 1}).status_code == 404
    assert c.get(f'/api/v1/files/{project_entry["latest"]["fileId"]}').status_code == 404
    assert c.get(f'/api/v1/files/{project_entry["latest"]["fileId"]}/content').status_code == 404

    # 公司共享只解除项目成员约束，仍按 internal 的来源应用权限判断。
    assert c.get(f'{BASE}/entries/{shared_entry["id"]}').status_code == 200
    assert c.get(f'{BASE}/entries/{shared_entry["id"]}/versions/1/content').status_code == 200
    assert c.get(f'/api/v1/files/{shared_entry["latest"]["fileId"]}').status_code == 200
    assert c.get(f'/api/v1/files/{shared_entry["latest"]["fileId"]}/content').status_code == 200
    audit = c.app.state.platform.store.audit_list(limit=100)
    assert any(item['action'] == 'knowledge.entry.update'
               and item['detail'].get('fields') == ['scope']
               and item['detail'].get('scope') == 'company' for item in audit)


def test_entry_without_project_keeps_legacy_file_project_guard(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    entry = upload(c, title='无 project 存量条目（合成）').json()
    file_id = entry['latest']['fileId']
    login(c, 'samplereviewer')
    assert publish(c, entry['id'], 1).status_code == 200

    store = c.app.state.platform.store
    with store._lock, store._db:
        row = store._db.execute('select document from kb_entries where id=?', (entry['id'],)).fetchone()
        entry_doc = json.loads(row[0])
        entry_doc.pop('project')
        entry_doc.pop('scope')
        store._db.execute('update kb_entries set document=? where id=?',
                          (json.dumps(entry_doc, ensure_ascii=False), entry['id']))
        file_row = store._db.execute('select document from v1_files where id=?', (file_id,)).fetchone()
        file_doc = json.loads(file_row[0])
        file_doc['project'] = 'limited-project'
        store._db.execute('update v1_files set project=?,document=? where id=?',
                          ('limited-project', json.dumps(file_doc, ensure_ascii=False), file_id))

    assert c.get(f'{BASE}/entries/{entry["id"]}').status_code == 200
    assert c.get(f'{BASE}/entries/{entry["id"]}/versions/1/content').status_code == 200
    assert c.get(f'/api/v1/files/{file_id}').status_code == 404
    assert c.get(f'/api/v1/files/{file_id}/content').status_code == 404


def test_snapshot_has_no_default_knowledge_seed(make_client, monkeypatch):
    monkeypatch.setenv("HAIKNOW_KB_SEED", "1")
    client = make_client()
    login(client, "sampleadmin")
    response = client.get(f"{BASE}/entries", params={"includeUnpublished": True})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert client.app.state.platform.store._db.execute("select count(*) from kb_versions").fetchone() == (0,)
