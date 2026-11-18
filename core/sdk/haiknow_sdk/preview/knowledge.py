"""实验性知识库句柄；平台上下文决定调用人与来源应用。

用法（应用后端）：

    ctx.preview.knowledge.upload('标准.pdf', data, title='检验依据', category='01-制度标准通知')
"""


class Knowledge:
    def __init__(self, service, user, app_id):
        self._service, self._user, self._app_id = service, user, app_id

    def _body(self, values):
        return {'sourceApp': self._app_id, **values}

    def upload(self, name, data, *, title, category, tags=(), visibility='internal', roles=(),
               departments=(), note='', text='', project=None, scope='project'):
        """上传原件并登记为知识库条目（版本 1，状态未审核）；scope=company 需发布权限。"""
        return self._service.create_entry(
            self._user, self._body({'title': title, 'category': category, 'tags': list(tags),
                                    'project': project, 'scope': scope, 'visibility': visibility, 'roles': list(roles),
                                    'departments': list(departments), 'note': note, 'text': text}),
            upload=(name, data))

    def register(self, file_id, *, title, category, tags=(), visibility='internal', roles=(),
                 departments=(), note='', text='', scope='project'):
        """把本应用已上传的 v1 原件登记为知识库条目；scope=company 需发布权限。"""
        return self._service.create_entry(
            self._user, self._body({'title': title, 'category': category, 'tags': list(tags),
                                    'scope': scope, 'visibility': visibility, 'roles': list(roles),
                                    'departments': list(departments), 'note': note, 'text': text}),
            file_id=file_id)

    def add_version(self, entry_id, name, data, *, note='', text='', project=None):
        return self._service.add_version(
            self._user, entry_id, {'note': note, 'text': text, 'project': project},
            upload=(name, data))

    def register_version(self, entry_id, file_id, *, note='', text=''):
        return self._service.add_version(
            self._user, entry_id, {'note': note, 'text': text}, file_id=file_id)

    def list(self, **filters):
        return self._service.search(self._user, filters)

    def get(self, entry_id):
        return self._service.get(self._user, entry_id)

    def references(self, entry_id):
        return self._service.references(self._user, entry_id)

    def record_files(self, app_id, record_id, version):
        return self._service.record_files(self._user, app_id, record_id, version)

    def submit(self, entry_id, version):
        return self._service.submit(self._user, entry_id, {'version': version})

    def publish(self, entry_id, version):
        return self._service.publish(self._user, entry_id, {'version': version})

    def update(self, entry_id, **patch):
        return self._service.update(self._user, entry_id, patch)

    def read(self, entry_id, version=None):
        return self._service.read(self._user, entry_id, version)[0]
