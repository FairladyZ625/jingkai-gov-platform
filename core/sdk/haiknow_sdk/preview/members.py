"""项目成员权限查询 preview 句柄。"""


class Members:
    def __init__(self, service, user, app_id):
        self._service, self._user, self._app_id = service, user, app_id

    def list(self, project, *, action='approve'):
        """列出项目内对当前应用具备 action 的在用成员。"""
        return self._service.list_members(self._user, self._app_id, project, action)
