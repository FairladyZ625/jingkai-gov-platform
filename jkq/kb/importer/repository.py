"""导入事务契约及用于独立验证的内存实现。"""

from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager, contextmanager
from copy import deepcopy
from threading import Lock
from typing import Protocol


class ImportTransaction(Protocol):
    def candidates(self, space: str) -> Sequence[dict]:
        """返回该空间未删除的文档，包括旧版。至少提供 id、space、title、text、source、status、version。"""
        ...

    def mark_replaced(self, document_id: str, replacement_id: str) -> None:
        """将旧版状态设为「已更新」并记录新版标识。"""
        ...

    def insert(self, document: dict) -> None:
        """保存新版或新文档及其正文、切片和导入者标识。"""
        ...


class ImportRepository(Protocol):
    def transaction(self, *, write: bool) -> AbstractContextManager[ImportTransaction]:
        """读操作使用同一视图。写事务须串行化候选查询与变更，并在异常时回滚。"""
        ...


class _MemoryTransaction:
    def __init__(self, documents):
        self._documents = documents

    def candidates(self, space):
        return [deepcopy(doc) for doc in self._documents.values() if doc["space"] == space]

    def mark_replaced(self, document_id, replacement_id):
        self._documents[document_id] = {
            **self._documents[document_id], "status": "已更新", "replacedBy": replacement_id,
        }

    def insert(self, document):
        if document["id"] in self._documents:
            raise ValueError("资料编号重复")
        self._documents[document["id"]] = deepcopy(document)


class MemoryImportRepository:
    """用于路由联调和测试的存储桩，进程退出后数据丢失。"""

    def __init__(self, documents: Iterable[dict] = ()):
        self._lock = Lock()
        self._documents = {doc["id"]: deepcopy(doc) for doc in documents}

    @contextmanager
    def transaction(self, *, write):
        with self._lock:
            working = self._documents.copy()
            yield _MemoryTransaction(working)
            if write:
                self._documents = working
