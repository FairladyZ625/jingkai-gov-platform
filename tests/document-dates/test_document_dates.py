from pathlib import Path
import subprocess


def test_document_dates():
    suite = Path(__file__).with_name("document-dates.test.cjs")
    subprocess.run(["node", "--test", str(suite)], check=True)
