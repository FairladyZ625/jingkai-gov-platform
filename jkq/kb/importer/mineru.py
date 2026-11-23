"""将本次公开上传交给已配置的 MinerU 路由。"""

import asyncio
import hashlib
from uuid import uuid4

from haiknow_core.aihub.errors import AIError
from haiknow_core.aihub.gateway import Gateway


class _MineruGateway(Gateway):
    def _route_candidates(self, capability, model=None):
        candidates = [(provider, model_id) for provider, model_id
                      in super()._route_candidates(capability, model) if provider["kind"] == "mineru"]
        if not candidates:
            raise AIError("not_configured", "未配置可用的 MinerU 解析路由")
        return candidates


class _UploadFile:
    def __init__(self, user, name, content):
        self.owner = user.id
        self.id = str(uuid4())
        self.metadata = dict(name=name, sha256=hashlib.sha256(content).hexdigest(), size=len(content))
        self.content = content

    def get_file(self, user, identity):
        if (user.id, identity) != (self.owner, self.id):
            raise AIError("not_found", "上传文件不存在")
        return self.metadata

    def read_file(self, user, identity):
        self.get_file(user, identity)
        return self.content


def parser_for(platform, user, space, classification):
    if space != "policy" or classification != "public":
        return None

    async def parse(name, ext, content, classification):
        if ext != "pdf":
            return None
        source = _UploadFile(user, name, content)
        gateway = _MineruGateway(platform.model.aihub.settings, files=source, audit=platform.store.audit)
        try:
            response = await asyncio.to_thread(
                gateway.call, "kb", "parse", {"file_id": source.id, "classification": classification},
                14, principal=user,
            )
        except AIError as exc:
            if exc.kind in ("not_configured", "outbound_denied"):
                return None
            raise
        platform.store.audit("kb", user.id, "ai.parse",
                             {"provider": response["provider"], "model": response["model"]})
        return "\n".join(block["text"] for block in response["result"]["blocks"] if block.get("text"))

    return parse
