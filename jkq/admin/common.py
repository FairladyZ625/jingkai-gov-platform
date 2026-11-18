"""管理变更统一加锁、校验和留痕。"""

from contextlib import contextmanager

from jkq.auth import ROLE_ORDER, AuthError

VIA = frozenset({'ui', 'chat', 'operator', 'api', 'computer'})


@contextmanager
def write(platform, user):
    store = platform.store
    with store._lock, store._db as db:
        store.begin_write()
        if 'admin' not in platform.rbac.actions(user, '*'):
            raise AuthError(403, 'FORBIDDEN', '当前角色缺少所需权限', app='*', need='admin')
        yield db


def record_change(platform, db, user, request, *, action, target, before, after, app='platform', metadata=None):
    roles = platform.directory.roles_of(user.id)
    role = next((role for role in ROLE_ORDER if role in roles), min(roles, default=None))
    via = request.headers.get('x-audit-via', 'api')
    platform.store.audit(app, user.id, action, {
        **(metadata or {}),
        'target': target, 'before': before, 'after': after,
        'via': via if via in VIA else 'api', 'role': role, 'user': user.name,
    }, connection=db)
