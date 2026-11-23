"""给润色预览和两稿比对生成同一种字符差异。"""

from difflib import SequenceMatcher


def parts(before: str, after: str) -> list[dict[str, str]]:
    if before == after:
        return [{"op": "eq", "t": before}] if before else []

    result = []
    for tag, a_start, a_end, b_start, b_end in SequenceMatcher(None, before, after).get_opcodes():
        if tag == "equal":
            result.append({"op": "eq", "t": before[a_start:a_end]})
        if tag in ("delete", "replace"):
            result.append({"op": "del", "t": before[a_start:a_end]})
        if tag in ("insert", "replace"):
            result.append({"op": "add", "t": after[b_start:b_end]})
    return result


def compare(before: str, after: str) -> dict:
    changes = parts(before, after)
    stats = {"add": 0, "del": 0}
    for part in changes:
        if part["op"] in stats:
            # 计数与原型的 JavaScript String.length 一致。
            stats[part["op"]] += len(part["t"].encode("utf-16-le")) // 2
    return {"parts": changes, "stats": stats}
