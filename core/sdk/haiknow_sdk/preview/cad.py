"""实验性 CAD 只读解析句柄（CAP-05 第一阶段）：DXF 与 STEP 的字段候选、对象定位与未覆盖范围。

用法（应用后端）：

    result = ctx.preview.cad.parse(entry['id'])
    result['fields']            # 图号、修订、名称等候选，带块名/属性标签/句柄出处
    result['source']['sha256']  # 知识库版本的原件校验值；原件不被改写

输入是知识库条目 ID（可选版本），平台按条目可见范围与发布状态校验；DWG 需要外部转换器，
本能力只返回明确的中文原因，不接外部进程。
"""


class CadError(Exception):
    """kind: unsupported_format / parse_failed / too_large / timeout / forbidden / not_found"""

    def __init__(self, kind: str, message: str, retryable: bool = False, **details):
        super().__init__(message)
        self.kind, self.retryable, self.details = kind, retryable, details


class Cad:
    def __init__(self, service, user, app_id):
        self._service, self._user, self._app_id = service, user, app_id

    def status(self):
        """支持的格式、解析器版本与限制；DWG 在这里给出不接入的原因。"""
        return self._service.status()

    def parse(self, entry_id, *, version=None):
        """解析知识库条目的原件，返回结构化候选；不改原件、不访问网络。"""
        return self._service.parse(self._user, {
            'appId': self._app_id, 'entryId': entry_id, 'version': version})