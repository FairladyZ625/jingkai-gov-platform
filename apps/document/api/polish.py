"""公文润色预览使用离线 mock provider。"""

from . import diff

_SUBSTITUTIONS = {
    "formal": (("咱们", "我局"), ("赶紧", "及时"), ("弄好", "完成"),
               ("马上", "尽快"), ("问一下", "咨询"), ("帮忙", "协助")),
    "concise": (("经认真研究，", ""), ("相关的", "相关"), ("进行申报", "申报")),
}


def mock_polish(text: str, style: str) -> str:
    for original, replacement in _SUBSTITUTIONS[style]:
        text = text.replace(original, replacement)
    return text


def preview(content: dict, style: str, para: int | None) -> dict:
    original = content["paragraphs"]
    revised = [mock_polish(text, style) if para is None or index == para else text
               for index, text in enumerate(original)]
    return {
        "preview": {**content, "paragraphs": revised},
        "parts": diff.parts("\n".join(original), "\n".join(revised)),
        "changed": revised != original,
    }
