#!/usr/bin/env python3
"""从仓库种子生成 file:// 模式直接加载的脚本。"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / "data/seed"
OUTPUT = ROOT / "prototype/v4/config/mock-data.js"


def read_seed(name):
    return json.loads((SEED / f"{name}.json").read_text(encoding="utf-8"))


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def main():
    demo = read_seed("demo")
    examples = read_seed("policy-examples")
    real = read_seed("real-policies")
    source = [
        "/* 由 prototype/v4/mock/build_mock.py 生成。请编辑 data/seed/ 中的 JSON。 */",
        "(() => {",
        f"const demo = {dump(demo)};",
        f"const examples = {dump(examples)};",
        f"const real = {dump(real)};",
        "window.JK_DATA = {",
        "  ...demo,",
        "  policyDocs: [...examples.policyDocs, ...real.policyDocs],",
        "  policies: [...examples.policies, ...real.policies],",
        "  realNotices: real.notices,",
        "  realNews: real.news,",
        "  departmentsReal: real.departments,",
        "  districtFacts: real.facts,",
        "};",
        "window.JK_REAL = real;",
        f"window.JK_REAL_KB = {dump(read_seed('real-kb'))};",
        f"window.JK_KB_EXAMPLES = {dump(read_seed('kb-examples'))};",
        "})();",
        "",
    ]
    OUTPUT.write_text("\n".join(source), encoding="utf-8")
    print(f"已生成 {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
