"""从仓库公开快照生成四份种子与 file:// 可加载的原型副本。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {
    "gongwen": "wenzhong title doc_no issuer date region full_text attachments note",
    "rules": "type title status doc_no issuer date full_text attachments source_site",
    "minutes": "meeting_type title date source full_text format",
    "enterprises": "name industry honor_or_list year source_type source_title source_date issuer attachment_url",
}


def convert(group, item):
    record = {key: item[key] for key in FIELDS[group].split() if key in item}
    verified = False
    if group == "gongwen":
        tags = ["公文范文", item["wenzhong"]]
        if "非北京" in item["note"]:
            tags.append("格式参考（非北京）")
        if "新闻通稿" in item["note"]:
            tags.append("新闻通稿")
    elif group == "rules":
        tags = ["部门制度", item["type"]]
        if item["status"].startswith("已失效"):
            tags.append("已失效")
    elif group == "minutes":
        tags = ["会议素材", "新闻通稿", item["meeting_type"]]
    else:
        verified = item["honor_verified"]
        tags = ["企业公开名单参考库", "已核实" if verified else "未核实"]
    return dict(record, source_url=item["source_url"], fetched=item["crawled"],
                tags=tags, verified=verified)


def build(root=ROOT):
    collections = {}
    dest = root / "data/seed/real"
    dest.mkdir(parents=True, exist_ok=True)
    for group in FIELDS:
        filename = group + ".json"
        source = json.loads((root / "data/public" / filename).read_text(encoding="utf-8"))
        records = [convert(group, item) for item in source["items"]]
        (dest / filename).write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        collections[group] = records
    script = "/* 由 scripts/data/build_real_supplement.py 生成。 */\nwindow.JK_REAL_SUPPLEMENT = "
    (root / "web/data/real-supplement.js").write_text(
        script + json.dumps(collections, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")


if __name__ == "__main__":
    build()
