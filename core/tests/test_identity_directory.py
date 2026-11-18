"""身份目录使用数据库真源；种子只在首次初始化或发现新应用时写入。"""
import json
import shutil

import yaml

from conftest import ROOT
from haiknow_core.store import Store


def test_seed_once_and_live_directory(tmp_path, isolated_platform):
    from haiknow_core.identity import Directory
    from haiknow_core.rbac import Rbac
    from haiknow_core.projects import Projects
    config = tmp_path / 'config'
    shutil.copytree(isolated_platform[0], config)
    store = Store(tmp_path / 'data')
    manifest = {'id': 'sample', 'defaultRoles': {'sampleoperator': ['view', 'operate']}}
    directory = Directory(store)
    directory.seed(config, [manifest], demo=True)
    rbac = Rbac(directory)
    user = rbac.users['sampleoperator']
    assert rbac.actions(user, 'sample') == frozenset({'view', 'operate'})
    assert directory.roles_of(user.id) == frozenset({'sampleoperator'})
    with store._db:
        store._db.execute("insert into departments values ('quality','质量部',null)")
        store._db.execute("insert into user_departments values ('sampleoperator','quality')")
        store._db.execute("delete from role_grants where role_id='sampleoperator' and app_id='sample'")
        store._db.execute("update users set name='新名称' where id='sampleoperator'")
    assert directory.departments_of(user.id) == frozenset({'quality'})
    assert directory.departments_of('missing') == frozenset()
    assert rbac.actions(user, 'sample') == frozenset()
    assert rbac.users[user.id].name == '新名称'
    # 已初始化的目录不再读取 yaml，也不覆盖被管理员清空的授权。
    for path in config.glob('*.yaml'):
        path.write_text('这不是合法的种子: [')
    directory.seed(config, [manifest], demo=True)
    assert rbac.actions(user, 'sample') == frozenset()
    directory.seed(config, [manifest, {'id': 'new-app', 'defaultRoles': {'sampleoperator': ['view']}}], demo=True)
    assert rbac.actions(user, 'new-app') == frozenset({'view'})
    projects = Projects(directory)
    assert projects.visible(user, 'sample-project')
    assert not projects.visible(user, 'limited-project')
    with store._db:
        store._db.execute("insert into project_members values ('limited-project','sampleoperator')")
    assert projects.visible(user, 'limited-project')
    assert projects.tree(user)['companies'][0]['projects'][0]['products']
    # 同一个库的新连接也能看到变更。
    reopened = Directory(Store(tmp_path / 'data'))
    assert reopened.departments_of(user.id) == frozenset({'quality'})


def test_production_seed_leaves_first_admin_for_bootstrap(tmp_path, isolated_platform):
    from haiknow_core.identity import Directory
    directory = Directory(Store(tmp_path))
    directory.seed(isolated_platform[0], [], demo=False)
    assert directory.users() == {}
    assert directory.company()['name'] == '虚构测试机构'
    assert directory.projects()


def test_demo_seed_reconciles_missing_users_without_touching_existing_ids(tmp_path, isolated_platform):
    from haiknow_core.identity import Directory
    from haiknow_core.passwords import hash_password

    config = tmp_path / 'config'
    shutil.copytree(isolated_platform[0], config)
    users = yaml.safe_load((config / 'users.yaml').read_text(encoding='utf-8'))
    existing = {'id': 'sampleexisting', 'name': '样例当前用户'}
    newcomer = {'id': 'samplenew', 'name': '样例新增审核员', 'roles': ['sampleextra'],
                'projects': ['sample-project']}
    (config / 'users.yaml').write_text(json.dumps(users), encoding='utf-8')
    store = Store(tmp_path / 'data')
    directory = Directory(store)
    directory.seed(config, [], demo=True)
    with store._db:
        before = store._db.execute('select password_hash,name,demo from users where id="sampleoperator"').fetchone()
        store._db.execute(
            'insert into users values (?,?,?,?,?,null,0,0,0,0,0)',
            ('sampleexisting', 'real-user', '真实用户占位', hash_password('real-pass1'), 'active'),
        )
    users['users'].extend([existing, newcomer])
    (config / 'users.yaml').write_text(json.dumps(users), encoding='utf-8')
    directory.seed(config, [], demo=True)
    with store._db:
        after = store._db.execute('select password_hash,name,demo from users where id="sampleoperator"').fetchone()
        real = store._db.execute('select password_hash,name,demo from users where id="sampleexisting"').fetchone()
        assert store._db.execute('select id from users where id="samplenew"').fetchone()
        assert store._db.execute("select 1 from project_members where user_id='samplenew'").fetchone()
        assert store._db.execute("select 1 from role_grants where role_id='sampleextra' and app_id='sample-app' and action='approve'").fetchone()
    assert after == before
    assert real == (real[0], '真实用户占位', 0)
    assert directory.user('samplenew').name == '样例新增审核员'


def test_demo_seed_covers_published_apps_with_distinct_handlers_and_reviewers(tmp_path, isolated_platform):
    import json
    import yaml
    from haiknow_core.identity import Directory

    config = tmp_path / 'config'
    shutil.copytree(isolated_platform[0], config)
    store = Store(tmp_path / 'data')
    directory = Directory(store)
    manifests = []
    for path in sorted(isolated_platform[1].glob('*/app.json')):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if path.parent.name not in {'_template', 'sample-gallery', 'sample-components'}:
            manifests.append(manifest)
    assert len(manifests) == 2
    directory.seed(config, manifests, demo=True)
    seeded = yaml.safe_load((config / 'users.yaml').read_text(encoding='utf-8'))['users']
    with store._db:
        user_ids = {row[0] for row in store._db.execute("select id from users where demo=1")}
    for manifest in manifests:
        handlers = [u['id'] for u in seeded if u['id'] in user_ids and 'operate' in directory.actions(u['id'], manifest['id'])]
        reviewers = [u['id'] for u in seeded if u['id'] in user_ids and 'approve' in directory.actions(u['id'], manifest['id'])]
        assert handlers, f"{manifest['id']} 缺少演示办理人"
        assert reviewers, f"{manifest['id']} 缺少演示确认人"
        assert any(handler != reviewer for handler in handlers for reviewer in reviewers), \
            f"{manifest['id']} 办理人与确认人不能只由同一账号承担"


def test_demo_disabled_never_imports_users(tmp_path, isolated_platform):
    from haiknow_core.identity import Directory

    directory = Directory(Store(tmp_path / 'data'))
    directory.seed(isolated_platform[0], [], demo=False)
    assert directory.users() == {}


def test_identity_upgrade_preserves_published_schema_and_data(tmp_path, monkeypatch):
    from haiknow_core import migrations
    published = migrations.MIGRATIONS[:3]
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'MIGRATIONS', published)
        Store(tmp_path).kv_put('sample', 'kept', {'value': 1})
    upgraded = Store(tmp_path)
    assert upgraded.kv_get('sample', 'kept') == {'value': 1}
    assert upgraded._db.execute('select max(version) from schema_versions').fetchone() == (len(migrations.MIGRATIONS),)
    assert len(list((tmp_path / 'backups').glob('*-3.db'))) == 1
    frozen = json.loads((ROOT / 'tests/compat/schema-migrations.json').read_text())
    assert [list(m) for m in migrations.MIGRATIONS[:len(frozen)]] == frozen
