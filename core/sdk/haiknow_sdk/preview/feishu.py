"""实验性飞书消息句柄；调用人、应用与群授权由平台上下文决定。"""


class Feishu:
    def __init__(self, service, user, app_id):
        self._service, self._user, self._app_id = service, user, app_id

    def messages(self, **filters):
        """按群、时间、消息 ID 查询本应用获授权群的原消息。"""
        return self._service.messages_for_app(self._user, self._app_id, filters)

    def message(self, message_id):
        """读取一条原消息的正文、修订与采集状态。"""
        return self._service.message_for_app(self._user, self._app_id, message_id)

    def status(self):
        """返回凭据状态、本应用已授权群、消息计数与断线缺口。"""
        return self._service.status_for_app(self._user, self._app_id)