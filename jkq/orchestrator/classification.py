"""对发送给模型的会话内容应用最严格的密级。"""

from typing import Literal

Classification = Literal["public", "internal", "confidential"]
ORDER: tuple[Classification, ...] = ("public", "internal", "confidential")


def strictest(*values: object) -> Classification:
    levels = [ORDER.index(value) if value in ORDER else 2 for value in values]
    return ORDER[max(levels, default=0)]
