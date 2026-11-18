"""实验性数据集句柄；SDK 使用平台上下文用户和应用 ID。"""


class Datasets:
    def __init__(self, service, user, app_id):
        self._service, self._user, self._app_id = service, user, app_id

    def list(self):
        return self._service.list(self._user, self._app_id)

    def query(self, dataset_id, **options):
        return self._service.query(self._user, dataset_id, {**options, 'appId': self._app_id})


class Preview:
    def __init__(self, context):
        self._context = context

    @property
    def datasets(self):
        context = self._context
        return Datasets(context.records._s.datasets, context.user, context.app_id)

    @property
    def knowledge(self):
        from .knowledge import Knowledge
        context = self._context
        return Knowledge(context.records._s.knowledge, context.user, context.app_id)

    @property
    def ai_tools(self):
        from .ai_tools import AITools
        return AITools(self._context)

    @property
    def jobs(self):
        from .jobs import Jobs
        context = self._context
        return Jobs(context.records._s.jobs, context.user, context.app_id)

    @property
    def reviews(self):
        from .reviews import Reviews
        context = self._context
        return Reviews(context.records._s, context.user, context.app_id)

    @property
    def latex(self):
        from .latex import Latex
        context = self._context
        return Latex(context.records._s.latex, context.user, context.app_id)

    @property
    def cad(self):
        from .cad import Cad
        context = self._context
        return Cad(context.records._s.cad, context.user, context.app_id)

    @property
    def messages(self):
        from .messages import Messages
        context = self._context
        return Messages(context.records._s, context.user, context.app_id)

    @property
    def members(self):
        from .members import Members
        context = self._context
        return Members(context.records._s, context.user, context.app_id)

    @property
    def cross_project(self):
        from .cross_project import CrossProject
        context = self._context
        return CrossProject(context.records._s, context.user, context.app_id)

    @property
    def feishu(self):
        from .feishu import Feishu
        context = self._context
        return Feishu(context.records._s.feishu, context.user, context.app_id)

    @property
    def schedules(self):
        from .schedules import Schedules
        context = self._context
        return Schedules(context.records._s.schedules, context.user, context.app_id)
