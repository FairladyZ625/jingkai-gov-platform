"""附件原件只进入对话专用表，与 #21 消息共享一个写事务。"""
import re
import subprocess
from tempfile import TemporaryFile
from pathlib import PurePath
from urllib.parse import quote, urlsplit
from uuid import uuid4

MAX_BYTES = 10 * 1024 * 1024
AUDIO = "mp3 m4a wav aac ogg flac mp4 webm".split()
SUPPORTED = set(AUDIO + "pdf doc docx wps txt md xls xlsx csv jpg jpeg png".split())
TEXT = {"txt", "md", "csv"}
NUMBER = re.compile(r"[〔【\[]\d{4}[〕】\]]\s*\d+\s*号")

# #17 合入前的 §5.1 清单样本。接入 bridge.apps 后使用当前用户可见的清单。

def fallback_apps(user):
    manifests = []
    for app, extensions, match in (
        ("meeting", AUDIO, ""),
        ("policy", "pdf doc docx txt wps".split(), "政策|办法|细则|措施|实施意见|申报指南"),
        ("enterprise", "xlsx xls csv pdf doc docx txt jpg jpeg png".split(), "企业|走访|营业执照"),
        ("document", "doc docx txt pdf wps".split(), "通知|公文|意见|方案|函|报告|纪要"),
    ):
        manifests.append({"id": app, "accepts": [{"ext": extensions, "match": match}]})
    return {"items": manifests}


class InputError(ValueError):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def check_size(size):
    if size > MAX_BYTES:
        raise InputError(413, "FILE_TOO_LARGE", "附件过大，单次内容合计最多 10 MiB")


def classify(ext, sample, host, manifests):
    kinds = {"meeting": "audio", "policy": "policy", "enterprise": "visit", "document": "document"}
    candidates = []
    for manifest in manifests:
        app = manifest["id"]
        if not manifest.get("available", True):
            continue
        for rule in manifest.get("accepts", []):
            if ext and ext not in rule.get("ext", []):
                continue
            score = 0
            if app == "meeting" and ext in AUDIO:
                score = 3
            elif app == "policy" and (NUMBER.search(sample) or
                                      host == "beijing.gov.cn" or host.endswith(".beijing.gov.cn")):
                score = 3
            elif rule.get("match") and re.search(rule["match"], sample):
                score = 2
            elif ext and not rule.get("match"):
                score = 1
            if score:
                candidates.append((score, app))
    if not candidates:
        return "unknown", {"action": "ask", "app": None, "mode": "confirm", "confidence": 0,
                           "params": {}, "reason": "请确认此附件的用途，或选择仅入库"}
    _, app = max(candidates, key=lambda pair: pair[0])
    route = {"action": "open", "app": app, "confidence": 0.9, "reason": "符合应用接收规则",
             "params": {"tab": "visit"} if app == "enterprise" else {}}
    if app == "policy":
        route["alsoImport"] = {"lib": "policy"}
    return kinds.get(app, "document"), route


def pdf_sample(data):
    """Poppler 仅读首页。临时输出避免把整页解压文本载入 Python。"""
    if not data.startswith(b"%PDF-"):
        return ""
    with TemporaryFile() as output:
        try:
            result = subprocess.run(
                ["pdftotext", "-f", "1", "-l", "1", "-enc", "UTF-8", "-", "-"],
                input=data, stdout=output, stderr=subprocess.DEVNULL, timeout=4,
            )
        except subprocess.TimeoutExpired:
            return ""
        except FileNotFoundError:
            return ""
        output.seek(0)
        return output.read(4096).decode("utf-8", errors="ignore") if result.returncode == 0 else ""


def prepare(source, name, value, manifests):
    if source == "file":
        name = PurePath(name.replace("\\", "/")).name
        ext = PurePath(name).suffix.lower().lstrip(".")
        if ext not in SUPPORTED:
            raise InputError(415, "UNSUPPORTED_TYPE", "暂不支持此文件类型")
        data = value
    else:
        ext = ""
        data = value.encode("utf-8")
    check_size(len(data))
    host = ""
    if source == "url":
        try:
            url = urlsplit(value)
            host = url.hostname or ""
        except ValueError:
            host = ""
        if not host or url.scheme not in ("https", "http"):
            raise InputError(422, "CHECK_FAILED", "请提供有效的 HTTP 或 HTTPS 链接")
    sample = name
    if source != "file" or ext in TEXT:
        sample += " " + data[:4096].decode("utf-8", errors="ignore")
    elif ext == "pdf":
        sample += " " + pdf_sample(data)
    kind, route = classify(ext, sample, host, manifests)
    item = {"name": name, "kind": kind, "size": len(data)}
    if source != "file":
        item[source] = value
    return item, route


def attachments(detail):
    return [item for message in detail["messages"] for item in message.get("attachments", [])]


class AttachmentStore:
    def __init__(self, conversations):
        self.conversations = conversations
        self.db = conversations.db
        with conversations.transaction(write=True):
            self.db.execute("""create table if not exists jkq_attachment_content (
                id text primary key, conversation_id text not null references jkq_conversations(id),
                content blob not null
            )""")

    def append(self, owner, cid, blobs, items, routes):
        # #21 的 begin_write 复用现有事务。append_message 在最后核对所有者，
        # 将文件、消息和审计一起提交；中途异常会回滚整批。
        with self.conversations.transaction(write=True):
            self.db.executemany(
                "insert into jkq_attachment_content(id, conversation_id, content) values(?,?,?)",
                ((ident, cid, data) for ident, data in blobs),
            )
            self.conversations.append_message(owner, cid, role="user", content="添加了对话附件",
                                              attachments=items, routes=routes)

    def content(self, owner, cid, ident):
        with self.conversations.transaction():
            row = self.db.execute(
                """select a.content from jkq_attachment_content a
                   join jkq_conversations c on c.id=a.conversation_id
                   where c.owner=? and c.deleted=0 and c.id=? and a.id=?""",
                (owner, cid, ident),
            ).fetchone()
        return row[0] if row else None


def publish(user, cid, parts, store, apps, library=None):
    if library is not None and (not isinstance(library, str) or not library.strip()):
        raise InputError(422, "CHECK_FAILED", "资料库名称无效")
    manifests = apps(user)["items"]
    items, routes, blobs = [], [], []
    for source, name, value in parts:
        item, route = prepare(source, name, value, manifests)
        ident = uuid4().hex
        if source == "file":
            blobs.append((ident, value))
            item["url"] = f"/api/v1/conversations/{quote(cid, safe='')}/attachments/{ident}/content"
        item["id"] = ident
        route["attachmentId"] = ident
        if library and item["kind"] != "unknown":
            route["alsoImport"] = {"lib": library}
        items.append(item)
        routes.append(route)
    store.append(user.id, cid, blobs, items, routes)
    return {"items": items, "routes": routes}
