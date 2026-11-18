"""应用按能力调用 AI，不感知服务商。"""
class AIError(RuntimeError):
    """能力失败，kind 可区分配置、限额、输入及服务商错误。"""
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
        self.retryable = kind in ('timeout', 'provider_error')


class AI:
    def __init__(self, model):
        self._model = model

    def _call(self, capability, payload, timeout):
        return self._model._gw.aihub.call(self._model._app, capability, payload, timeout)

    def chat(self, messages, *, timeout=50, **options):
        return self._call('chat', {'messages': messages, **options}, timeout)

    def image(self, prompt, *, timeout=50, **options):
        return self._call('image', {'prompt': prompt, **options}, timeout)

    def transcribe(self, audio_base64, *, timeout=50, **options):
        return self._call('transcribe', {'audio_base64': audio_base64, **options}, timeout)

    def speech(self, text, *, timeout=50, **options):
        return self._call('speech', {'input': text, **options}, timeout)

    def embedding(self, text, *, timeout=50, **options):
        return self._call('embedding', {'input': text, **options}, timeout)
