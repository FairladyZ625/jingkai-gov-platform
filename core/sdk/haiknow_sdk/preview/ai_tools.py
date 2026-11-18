"""实验性 AI 工具句柄：文档解析、网络搜索、网页读取、读图识别。

服务商、密钥、配额与出站许可都由平台 AI 能力中心配置；应用只传文件 ID、查询词或网址。
"""


class AITools:
    def __init__(self, context):
        self._context = context

    def _call(self, capability, payload, timeout):
        gateway = self._context.model._gw.aihub
        return gateway.call(self._context.app_id, capability, payload, timeout, principal=self._context.user)

    def parse(self, file_id, *, classification='internal', timeout=50):
        """把平台文件解析成带页码的区块候选。"""
        return self._call('parse', {'file_id': file_id, 'classification': classification}, timeout)

    def search(self, query, *, count=None, classification='internal', timeout=50):
        """搜索公开网页，返回带来源与时间的结果候选。"""
        payload = {'query': query, 'classification': classification}
        if count is not None:
            payload['count'] = count
        return self._call('search', payload, timeout)

    def fetch(self, url, *, allowed_hosts=None, classification='internal', timeout=50):
        """读取公网网页；可用非空精确主机列表限制初始地址及跳转。"""
        payload = {'url': url, 'classification': classification}
        if allowed_hosts is not None:
            payload['allowed_hosts'] = allowed_hosts
        return self._call('fetch', payload, timeout)

    fetch_page = fetch

    def embedding(self, text, *, classification='internal', timeout=50):
        """按资料分级计算向量；稳定入口继续使用缺省 internal。"""
        return self._call('embedding', {'input': text, 'classification': classification}, timeout)

    def vision(self, file_id, instruction, *, classification='internal', timeout=50):
        """按任务说明读图，返回带位置与置信度的候选。"""
        return self._call('vision', {'file_id': file_id, 'instruction': instruction, 'classification': classification}, timeout)

    def transcribe(self, file_id, *, classification='internal', timeout=50):
        """按 CAP-09 原件引用转写 WAV、WebM、MP4 或 Ogg 音频。"""
        return self._call('transcribe', {'file_id': file_id, 'classification': classification}, timeout)
