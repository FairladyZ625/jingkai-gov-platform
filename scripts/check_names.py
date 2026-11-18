#!/usr/bin/env python3
"""对照公开企业名单并校验演示信用代码。"""

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = re.compile(r"DEMO-E[0-9]{3}")


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def normalize(name):
    return "".join(unicodedata.normalize("NFKC", name).split()).casefold()


def main():
    companies = read_json("data/seed/demo.json")["enterprises"]
    public = read_json("data/public/enterprises.json")["items"]
    public_names = {normalize(row["name"]) for row in public}
    hits = [
        (row["id"], row[field])
        for row in companies
        for field in ("name", "short")
        if normalize(row[field]) in public_names
    ]
    invalid = [
        row["id"] for row in companies
        if not CODE.fullmatch(row.get("creditCode", ""))
        or row["creditCode"] != f"DEMO-{row['id']}"
    ]
    print(f"示例企业 {len(companies)} 家，公开名单 {len(public)} 家，规范化精确匹配 {len(hits)} 命中。")
    for company_id, name in hits:
        print(f"名单重名 {company_id} {name}")
    print(f"示例信用代码 {len(companies) - len(invalid)}/{len(companies)} 通过正则校验。")
    for company_id in invalid:
        print(f"信用代码格式错误 {company_id}")
    return int(not companies or not public or bool(hits or invalid))


if __name__ == "__main__":
    sys.exit(main())
