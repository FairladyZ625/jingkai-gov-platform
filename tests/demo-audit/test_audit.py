from pathlib import Path
import subprocess


def test_policy_model_audit():
    subprocess.run(["node", "--test", Path(__file__).with_name("contract.cjs")], check=True)
