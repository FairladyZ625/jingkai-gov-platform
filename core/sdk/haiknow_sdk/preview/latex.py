"""实验性 LaTeX 文档编译句柄（CAP-08）：受管模板 + 结构化字段 → PDF，登记进知识库。

用法（应用后端，长耗时请放在 jobs 的步骤里）：

    result = ctx.preview.latex.render('official-notice', {'title': '…', 'body': '…'},
                                      project='P-001', doc_title='设备点检通知', category='01-制度标准通知')
    result['entry']['id'], result['version'], result['sha256']

应用不能提交原始 LaTeX，只能引用平台管理员登记的模板；失败不产生任何文件。
"""


class LatexError(Exception):
    """kind: not_configured / forbidden / bad_input / not_found / compile_failed / timeout / too_large / busy"""

    def __init__(self, kind: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.kind, self.retryable = kind, retryable


class Latex:
    def __init__(self, service, user, app_id):
        self._service, self._user, self._app_id = service, user, app_id

    def templates(self):
        return self._service.list_templates(self._user)

    def render(self, template, fields, *, project, doc_title, category='01-制度标准通知', version=None,
               entry_id=None, note='', tags=(), visibility='internal'):
        """编译并登记；entry_id 给出时作为该条目的新版本，否则新建条目。"""
        return self._service.render(self._user, {
            'appId': self._app_id, 'template': template, 'fields': fields, 'project': project,
            'title': doc_title, 'category': category, 'version': version, 'entryId': entry_id,
            'note': note, 'tags': list(tags), 'visibility': visibility})
