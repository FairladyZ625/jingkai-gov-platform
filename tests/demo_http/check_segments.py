"""只接受脚本中全部十二个具名段落各通过一次。"""

import re
import sys
from pathlib import Path
from xml.etree import ElementTree

SCRIPT = Path(__file__).resolve().parents[2] / "prototype/v4/config/demo-script.js"


def main(path):
    titles = re.findall(r"\{ title: '([^']+)', steps:", SCRIPT.read_text(encoding="utf-8"))
    titles_by_id = {title.encode("unicode_escape").decode(): title for title in titles}
    cases = [case for case in ElementTree.parse(path).iter("testcase")
             if case.get("name", "").startswith("test_segment[")]
    passed = set()
    for case in cases:
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error")):
            continue
        ident = case.get("name").removeprefix("test_segment[").removesuffix("]")
        passed.add(titles_by_id.get(ident, ident))
    missing = [title for title in titles if title not in passed]
    print(f"HTTP 演示通过 {len(set(titles) & passed)}/12 段；收集 {len(cases)} 段")
    if missing:
        print("未通过：" + "、".join(missing))
    return int(len(cases) != 12 or len(set(titles)) != 12 or passed != set(titles))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
