"""让无浏览器的 pytest 与 demo-http CI 都执行 JavaScript 契约回归。"""
from pathlib import Path
import subprocess


def test_review_http_contract():
    subprocess.run(["node", "--test", str(Path(__file__).with_name("review-transport.test.cjs"))], check=True)
