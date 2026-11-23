"""按应用主体键跨项目只读读取的 preview 句柄。"""


class CrossProject:
    def __init__(self, service, user, app_id):
        self._service, self._user, self._app_id = service, user, app_id

    def records(self, subject, **filters):
        return self._service.list_cross_records(self._user, self._app_id, subject, **filters)

    def get(self, record_id, version=None):
        return self._service.get_cross_record(self._user, self._app_id, record_id, version)

    def read_file(self, file_id):
        return self._service.read_cross_file(self._user, self._app_id, file_id)
