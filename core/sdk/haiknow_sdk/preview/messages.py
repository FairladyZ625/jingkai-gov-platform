"""应用内消息实验句柄；发送应用、用户与权限均由平台上下文决定。"""


class Messages:
    def __init__(self, service, user, app_id):
        self._service, self._user, self._app_id = service, user, app_id

    def send(self, *, idempotency_key, recipient_ids, record_id, version, title, body,
             priority='normal', expires_at=None, requires_acknowledgement=False):
        return self._service.send_message(self._user, self._app_id, {
            'idempotencyKey': idempotency_key, 'recipientIds': recipient_ids,
            'recordId': record_id, 'version': version, 'title': title, 'body': body,
            'priority': priority, 'expiresAt': expires_at,
            'requiresAcknowledgement': requires_acknowledgement,
        })

    def inbox(self):
        return self._service.list_messages(self._user)

    def get(self, message_id):
        return self._service.get_message(self._user, message_id)

    def read(self, message_id):
        return self._service.read_message(self._user, message_id)

    def acknowledge(self, message_id):
        return self._service.acknowledge_message(self._user, message_id)

    def sent(self):
        return self._service.list_sent_messages(self._user, self._app_id)
