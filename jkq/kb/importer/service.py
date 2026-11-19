"""导入预览、权限检查及事务内去重和换版。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePath
import re
import unicodedata
from urllib.parse import urlsplit
from uuid import uuid4

from .analysis import KINDS, analyze_document
from .parsing import ParseError, parse_document
from .public_url import PublicURLReader
from .repository import ImportRepository

SPACE_NAMES = {"policy": "政策库", "template": "公文范文", "minutes": "会议纪要",
               "rules": "部门制度", "enterprise": "企业档案"}
CLASSIFICATIONS = ("public", "internal", "confidential")
ORIGINS = ("官网", "上传", "粘贴", "网址", "对话", "企业管理")
ITEM_FIELDS = {
    "key", "name", "ext", "size", "from", "parse", "text", "url", "meta", "tags", "classification",
    "fileIndex", "decision", "skip", "dup", "ok", "chars", "chunks", "chunkPreview", "stages", "real",
    "file", "error",
}
BATCH_FIELDS = {"items", "space", "from", "classification"}
OPTIONAL_TEXT_FIELDS = frozenset({"text", "title", "url"})
META_FIELDS = {"title", "space", "kind", "docNo", "org", "date", "status", "url", "expire"}
MAX_ITEMS = 32


class ImportFailure(Exception):
    def __init__(self, status, code, message, **details):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


def invalid(message):
    return ImportFailure(422, "CHECK_FAILED", message)


@dataclass(frozen=True)
class SpaceAccess:
    readable: frozenset[str]
    writable: frozenset[str]


@dataclass(frozen=True)
class Upload:
    name: str
    content: bytes


@dataclass
class _Prepared:
    item: dict
    chunks: list[dict]
    decision: str
    expected_version: dict


def _mapping(value, allowed, message):
    if not isinstance(value, dict) or value.keys() - allowed:
        raise invalid(message)


def _classification(value):
    if value not in CLASSIFICATIONS:
        raise invalid("密级只能是 public、internal 或 confidential")
    return value


def _string(value, label, *, required=False, limit=2048):
    if (not isinstance(value, str) or len(value) > limit or (required and not value.strip())
            or re.search(r"[\x00-\x1f\x7f\ud800-\udfff]", value)):
        raise invalid(f"{label}格式无效")
    return value.strip()


def _origin(value):
    if value not in ORIGINS:
        raise invalid("资料来源类型无效")
    return value


def _space(access, space):
    if not isinstance(space, str) or space not in KINDS:
        raise invalid("未知知识库空间")
    if space not in access:
        raise ImportFailure(403, "FORBIDDEN", "没有该知识库空间的读取和导入权限")
    return space


def _normalized(value):
    return unicodedata.normalize("NFKC", value).casefold()


def _doc_number(value):
    return re.sub(r"\s+", "", _normalized(value)).translate(str.maketrans("〔〕【】", "[][]"))


def _title_tokens(title):
    tokens = set()
    for token in re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+(?:\.[0-9]+)?", _normalized(title)):
        if len(token) > 1 and "\u3400" <= token[0] <= "\u9fff":
            tokens.update(token[i:i + 2] for i in range(len(token) - 1))
        else:
            tokens.add(token)
    return tokens


def _similarity(title, tokens, candidate):
    if _normalized(title) == _normalized(candidate):
        return 1.0
    other = _title_tokens(candidate)
    return len(tokens & other) / (len(tokens | other) or 1)


def _version_hint(doc, score):
    return dict(type="version", id=doc["id"], title=doc["title"], sim=round(score * 100),
                oldDate=doc["source"].get("date", ""), oldVersion=doc["version"])


class ImportService:
    def __init__(self, repository: ImportRepository, spaces_for, *, reader=None,
                 parser_for=None, title_threshold=0.62):
        if not 0 < title_threshold <= 1:
            raise ValueError("标题相似度阈值须大于 0 且不超过 1")
        self._repository = repository
        self._spaces_for = spaces_for
        self._reader = reader if reader is not None else PublicURLReader()
        self._parser_for = parser_for
        self._title_threshold = title_threshold

    def _access(self, user):
        if user is None:
            raise ImportFailure(401, "UNAUTHENTICATED", "请先登录")
        grant = self._spaces_for(user)
        allowed = grant.readable & grant.writable
        if not allowed:
            raise ImportFailure(403, "FORBIDDEN", "没有可读取和导入的知识库空间")
        return allowed

    def _match(self, view, item):
        meta = item["meta"]
        docs = [doc for doc in view.candidates(meta["space"]) if doc["space"] == meta["space"]]
        for doc in docs:
            if doc["text"].strip() == item["text"]:
                return dict(type="duplicate", id=doc["id"], title=doc["title"]), None

        doc_no = _doc_number(meta["docNo"])
        title = meta["title"]
        tokens = _title_tokens(title)
        best, rank = None, ()
        for doc in docs:
            if doc.get("replacedBy") or doc["status"] == "已更新":
                continue
            same_no = bool(doc_no and doc_no == _doc_number(doc["source"].get("docNo", "")))
            score = 1.0 if same_no else _similarity(title, tokens, doc["title"])
            candidate_rank = (same_no, score, doc["version"], doc["id"])
            if score >= self._title_threshold and candidate_rank > rank:
                best, rank = doc, candidate_rank
        if best is not None:
            return _version_hint(best, rank[1]), best
        return {"type": "new"}, None

    async def _prepare(self, user, value, access, default_space, fallback_origin, default_class, *, upload=None):
        _mapping(value, ITEM_FIELDS, "导入条目格式无效或包含未知字段")
        classification = _classification(value.get("classification", default_class or "internal"))
        if default_class is not None:
            classification = max(classification, default_class, key=CLASSIFICATIONS.index)
        meta = value.get("meta", {})
        _mapping(meta, META_FIELDS, "导入元数据格式无效或包含未知字段")
        overrides = {key: _string(entry, "元数据", limit=8192 if key == "url" else 2048)
                     for key, entry in meta.items()}
        if "space" in overrides:
            _space(access, overrides["space"])
        if default_space is not None:
            overrides["space"] = default_space
        if overrides.get("space") == "enterprise":
            classification = "confidential"

        decision = value.get("decision", "")
        if decision not in ("", "new", "version", "skip") or type(value.get("skip", False)) is not bool:
            raise invalid("导入决策只能是 new、version 或 skip，skip 须为布尔值")
        if value.get("skip"):
            decision = "skip"
        name = _string(value.get("name", upload.name if upload else ""), "文件名", required=True)
        # 原型会随已解析文本带上浏览器 File 的空 JSON 投影。
        if "file" in value and value["file"] != {}:
            raise invalid("请使用 multipart/form-data 上传文件")
        key = _string(value.get("key", str(uuid4())), "导入条目标识", required=True)
        ext = _string(value.get("ext", ""), "文件扩展名", limit=12)
        origin = _origin(value.get("from", fallback_origin))
        parse = value.get("parse", "real")
        if parse not in ("real", "simulated", "sample") or type(value.get("real", False)) is not bool:
            raise invalid("解析来源格式无效")
        size = value.get("size", 0)
        if type(size) is not int or size < 0:
            raise invalid("文件大小须为非负整数")
        if decision == "skip":
            return _Prepared({"name": name}, [], decision, {})

        source_url = _string(overrides.pop("url", value.get("url", "")), "来源网址", limit=8192)
        expected = value.get("dup", {})
        if not isinstance(expected, dict):
            raise invalid("查重提示须为对象")
        content = upload.content if upload is not None else None
        remote_parser = None
        if upload is not None:
            uploaded_ext = PurePath(upload.name).suffix.lower().lstrip(".")
            ext = ext.lower().lstrip(".")
            if uploaded_ext and ext and ext != uploaded_ext:
                raise invalid("文件扩展名与上传文件不一致")
            ext = uploaded_ext or ext
            parse, size = "real", len(content)
            if self._parser_for is not None and classification != "confidential":
                remote_parser = self._parser_for(user, overrides.get("space"), classification)
        try:
            text = await parse_document(
                name, ext=ext, text=value.get("text"), content=content, classification=classification,
                remote_parser=remote_parser,
            )
            if re.search(r"[\ud800-\udfff]", text):
                raise ParseError("正文含无效的 Unicode 字符")
        except ParseError as exc:
            raise ImportFailure(422, "PARSE_FAILED", str(exc)) from None

        try:
            result = analyze_document(name, text, overrides=overrides, source_url=source_url)
        except ValueError as exc:
            raise invalid(str(exc)) from None
        meta, chunks = result["meta"], result["chunks"]
        if meta["url"] and urlsplit(meta["url"]).username is not None:
            raise invalid("来源网址不能包含用户凭据")
        _space(access, meta["space"])
        if meta["space"] == "enterprise":
            classification = "confidential"
        tags = value.get("tags", result["tags"])
        if not isinstance(tags, list):
            raise invalid("标签须为数组")
        tags = [_string(tag, "标签", required=True) for tag in tags]
        item = {
            "key": key, "name": name, "ext": ext, "size": size or len(text.encode("utf-8")),
            "from": origin, "parse": parse, "classification": classification, "ok": True,
            "text": text, "chars": len(text), "meta": meta, "url": meta["url"],
            "real": value.get("real", False), "chunks": len(chunks), "tags": tags,
            "chunkPreview": [dict(head=c["head"], text=c["text"][:120]) for c in chunks[:3]],
            "stages": dict(parse="done", chunk="done", tag="done"),
        }
        return _Prepared(item, chunks, decision, expected)

    async def _prepare_batch(self, user, payload, access, files, *, one_step=False):
        if isinstance(payload, dict):
            # 原型适配层未填的 text/title/url 以 null 发送，与缺键同义；其他字段的 null 照常校验。
            payload = {key: value for key, value in payload.items()
                       if not (key in OPTIONAL_TEXT_FIELDS and value is None)}
        extra = {"text", "title", "url"} if one_step else set()
        _mapping(payload, BATCH_FIELDS | extra, "导入请求格式无效或包含未知字段")
        space = _space(access, payload["space"]) if "space" in payload else None
        classification = _classification(payload["classification"]) if "classification" in payload else None
        origin = _origin(payload.get("from", "上传"))
        items = payload.get("items", [])
        if not isinstance(items, list) or ("items" not in payload and not one_step):
            raise invalid("请提供待导入条目数组 items")
        if len(items) + ("text" in payload) + ("url" in payload) > MAX_ITEMS:
            raise invalid("单次最多导入 32 项资料")

        # fileIndex 指向同一请求内按传输顺序排列的 file 字段。每个文件必须引用一次。
        indexes = []
        for item in items:
            _mapping(item, ITEM_FIELDS, "导入条目格式无效或包含未知字段")
            if "fileIndex" in item:
                index = item["fileIndex"]
                if type(index) is not int or not 0 <= index < len(files):
                    raise invalid("文件编号 fileIndex 无效")
                indexes.append(index)
        if sorted(indexes) != list(range(len(files))):
            raise invalid("每个上传文件须对应一个导入条目")

        prepared = []
        for item in items:
            upload = files[item["fileIndex"]] if "fileIndex" in item else None
            prepared.append(await self._prepare(user, item, access, space, origin, classification, upload=upload))
        if one_step and "text" in payload:
            text_item = {"name": payload.get("title", "粘贴的文字"), "text": payload["text"],
                         "from": payload.get("from", "粘贴")}
            if "title" in payload:
                text_item["meta"] = {"title": payload["title"]}
            prepared.append(await self._prepare(user, text_item, access, space, origin, classification))
        if one_step and "url" in payload:
            prepared.append(await self._prepare_url(user, payload["url"], access, space, classification,
                                                    payload.get("from", "网址")))
        if one_step and not prepared:
            raise invalid("请提供待导入条目、正文或网址")
        return prepared

    async def _prepare_url(self, user, url, access, space, classification, origin="网址"):
        page = await self._reader.read(url)
        name = page.title[:2048] or urlsplit(page.url).hostname
        value = {"name": name, "text": page.text, "url": page.url, "from": origin, "real": True}
        if page.title:
            value["meta"] = {"title": name}
        return await self._prepare(user, value, access, space, origin, classification)

    def _preview(self, prepared):
        with self._repository.transaction(write=False) as view:
            for entry in prepared:
                item = entry.item
                item["dup"] = self._match(view, item)[0]

    async def preview(self, user, payload, *, files=()):
        prepared = await self._prepare_batch(user, payload, self._access(user), files)
        if any(entry.decision == "skip" for entry in prepared):
            raise invalid("请在确认入库时选择跳过")
        self._preview(prepared)
        return {"items": [entry.item for entry in prepared]}

    async def preview_url(self, user, payload):
        access = self._access(user)
        _mapping(payload, {"url", "space", "classification"}, "网址导入请求格式无效")
        space = _space(access, payload["space"]) if "space" in payload else None
        classification = _classification(payload["classification"]) if "classification" in payload else None
        entry = await self._prepare_url(user, payload.get("url"), access, space, classification)
        self._preview([entry])
        return {"item": entry.item, "snapshot": False}

    async def commit(self, user, payload, *, files=(), one_step=False):
        prepared = await self._prepare_batch(user, payload, self._access(user), files, one_step=one_step)
        docs, skipped = {}, []
        with self._repository.transaction(write=True) as view:
            for entry in prepared:
                item = entry.item
                if entry.decision == "skip":
                    skipped.append(dict(name=item["name"], reason="已选择跳过"))
                    continue
                hint, previous = self._match(view, item)
                if hint["type"] == "duplicate":
                    skipped.append(dict(name=item["name"], reason="已在库中"))
                    continue
                if entry.decision == "new" or (not one_step and not entry.decision):
                    previous = None
                elif entry.decision == "version":
                    expected = entry.expected_version
                    if previous is None or any(field in expected and hint[field] != expected[field]
                                               for field in ("id", "oldVersion")):
                        raise ImportFailure(409, "VERSION_CONFLICT", "换版目标已变化，请重新预览后确认")
                document = self._document(user, entry, previous)
                if previous is not None:
                    previous_id = previous["id"]
                    view.mark_replaced(previous_id, document["id"])
                    if previous_id in docs:
                        docs[previous_id].update(status="已更新", replacedBy=document["id"])
                view.insert(document)
                docs[document["id"]] = {key: value for key, value in document.items()
                                       if key not in ("text", "chunkList", "uploadedBy")}
        return dict(docs=list(docs.values()), chunks=sum(doc["chunks"] for doc in docs.values()), skipped=skipped)

    @staticmethod
    def _document(user, entry, previous):
        item = entry.item
        meta = item["meta"]
        source = {field: meta[field] for field in ("org", "date", "url", "docNo")}
        if previous is not None:
            for field in ("docNo", "org", "url"):
                source[field] = source[field] or previous["source"].get(field, "")
        document = {
            "id": f"KB-{uuid4()}", "title": meta["title"], "space": meta["space"],
            "spaceName": SPACE_NAMES[meta["space"]], "kind": meta["kind"],
            "status": meta["status"], "expire": meta["expire"], "source": source,
            "text": item["text"], "chunkList": entry.chunks, "chunks": item["chunks"],
            "tags": item["tags"], "parse": item["parse"], "real": item["real"], "example": False,
            "classification": item["classification"], "from": item["from"],
            "uploadedBy": user.id, "version": 1, "addedAt": datetime.now(timezone.utc).isoformat(),
        }
        if previous is not None:
            document.update(prev=previous["id"], version=previous["version"] + 1)
        return document
