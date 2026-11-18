"""角色 × 应用 × 动作；每次读取数据库目录，授权修改即时生效。"""
from haiknow_sdk import User


class Rbac:
    def __init__(self, directory):
        self.directory = directory
        # 可选的受众判断 (user, app_id) -> bool：草稿/灰度应用对受众之外的人没有任何动作。
        self.audience = None

    @property
    def users(self):
        return self.directory.users()

    @property
    def role_names(self):
        return self.directory.role_names()

    def actions(self, user: User, app_id: str) -> frozenset[str]:
        acts = self.directory.actions(user.id, app_id)
        if self.audience and app_id != '*' and 'admin' not in acts and not self.audience(user, app_id):
            return frozenset()
        return acts
