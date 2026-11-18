"""从专用 pytest JUnit 报告核对各段结果，漏收集及跳过均不能通过验收。"""

import sys
from xml.etree import ElementTree


def main(path):
    cases = [case for case in ElementTree.parse(path).iter("testcase")
             if case.get("name", "").startswith("test_segment[")]
    passed = [case.get("name") for case in cases
              if all(case.find(tag) is None for tag in ("skipped", "failure", "error"))]
    print(f"HTTP 演示通过 {len(set(passed))}/12 段；收集 {len(cases)} 段")
    return int(len(cases) != 12 or len(set(passed)) != 12)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
