from pathlib import Path
import subprocess


def test_extension_notice():
    suite = Path(__file__).with_name("extension-notice.test.cjs")
    subprocess.run(["node", "--test", str(suite)], check=True)
