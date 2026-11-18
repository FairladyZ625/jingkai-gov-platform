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
        "/* #81：若已加载 app.config，则模型/能力/审计模型名跟随 JK_CONFIG.modelRouting。 */",
        "const routing = window.JK_CONFIG && window.JK_CONFIG.modelRouting;",
        "if (routing) {",
        "  const modelName = (id) => routing.models.find((m) => m.id === id).name;",
        "  window.JK_DATA.models = routing.models;",
        "  window.JK_DATA.capabilities = routing.capabilities;",
        "  window.JK_DATA.audit = window.JK_DATA.audit.map((row) => {",
        "    const action = row[3];",
        "    let model = row[4];",
        "    if (/^(匹配|查看档案) ·/.test(action)) model = modelName(routing.channels.local);",
        "    else if (action.startsWith('生成初稿 ·')) model = modelName(routing.taskModels.writing);",
        "    else if (action.startsWith('创建草稿 ·')) model = modelName(routing.taskModels.rules);",
        "    else if (action.startsWith('转写 ·')) model = routing.transcriptionModel;",
        "    return [row[0], row[1], row[2], row[3], model];",
        "  });",
        "  window.JK_DATA.usage = {",
        "    ...window.JK_DATA.usage,",
        "    byModel: [...routing.usageBuckets.map(([id, share]) => [modelName(id), share]), ['其他', 5]],",
        "  };",
        "}",
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
