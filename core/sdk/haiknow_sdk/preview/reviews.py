"""自管审核决定的实验句柄；来源前置条件由平台在同一事务内核对。"""


class Reviews:
    def __init__(self, service, user, app_id):
        self._service, self._user, self._app_id = service, user, app_id

    def decide(self, review_id, *, version, decision, comment='', assignee=None, require=None):
        return self._service.decide_review(self._user, review_id, {
            'version': version, 'decision': decision, 'comment': comment,
            'assignee': assignee, 'require': require,
        }, app_id=self._app_id)
