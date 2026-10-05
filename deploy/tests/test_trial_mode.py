"""No network/containers: validate deployment decisions and reject unsafe demo credentials."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "trial-mode.py"


class TrialModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = {
            "SQLCHAT_TRIAL_ENABLED": "true",
            "SQLCHAT_TRIAL_BUILTIN_DB_NAME": "db-genius",
            "SQLCHAT_TRIAL_BUILTIN_HOST": "trial-mysql",
            "SQLCHAT_TRIAL_BUILTIN_PORT": "3306",
            "SQLCHAT_TRIAL_BUILTIN_USERNAME": "sqlchat_demo",
            "SQLCHAT_TRIAL_BUILTIN_PASSWORD": "a" * 48,
        }
        self.demo = {"MYSQL_ROOT_PASSWORD": "b" * 48, "TRIAL_PASSWORD": "a" * 48}

    def run_mode(self) -> subprocess.CompletedProcess[str]:
        document = {"services": {"api": {"environment": self.env},
                                  "trial-mysql": {"environment": self.demo}}}
        return subprocess.run([sys.executable, "-B", str(SCRIPT)], input=json.dumps(document),
                              capture_output=True, text=True, check=False)

    def test_off_needs_no_demo_credentials(self) -> None:
        self.env = {"SQLCHAT_TRIAL_ENABLED": "false"}
        self.demo = {}
        result = self.run_mode()
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "off"))

    def test_local_demo_selected(self) -> None:
        result = self.run_mode()
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "local"))

    def test_external_trial_does_not_require_local_root(self) -> None:
        self.env["SQLCHAT_TRIAL_BUILTIN_HOST"] = "mysql.example.test"
        self.env["SQLCHAT_TRIAL_BUILTIN_PASSWORD"] = "external'password"
        self.demo = {}
        result = self.run_mode()
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "external"))

    def test_invalid_boolean_rejected_before_deployment(self) -> None:
        self.env["SQLCHAT_TRIAL_ENABLED"] = "yes"
        self.assertNotEqual(self.run_mode().returncode, 0)

    def test_incomplete_trial_rejected(self) -> None:
        for suffix in ("DB_NAME", "HOST", "PORT", "USERNAME", "PASSWORD"):
            key = f"SQLCHAT_TRIAL_BUILTIN_{suffix}"
            saved = self.env[key]
            self.env[key] = ""
            with self.subTest(suffix=suffix):
                self.assertNotEqual(self.run_mode().returncode, 0)
            self.env[key] = saved

    def test_unsafe_local_identifiers_rejected_without_echoing_secrets(self) -> None:
        for suffix in ("DB_NAME", "USERNAME"):
            key = f"SQLCHAT_TRIAL_BUILTIN_{suffix}"
            saved = self.env[key]
            self.env[key] = "demo';DROP USER root;--"
            result = self.run_mode()
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(self.demo["MYSQL_ROOT_PASSWORD"], result.stderr)
            self.env[key] = saved

    def test_root_trial_account_rejected(self) -> None:
        self.env["SQLCHAT_TRIAL_BUILTIN_USERNAME"] = "root"
        self.assertNotEqual(self.run_mode().returncode, 0)

    def test_local_port_must_match_mysql(self) -> None:
        self.env["SQLCHAT_TRIAL_BUILTIN_PORT"] = "3307"
        self.assertNotEqual(self.run_mode().returncode, 0)

    def test_hex_password_required_for_safe_init_sql(self) -> None:
        for name in ("MYSQL_ROOT_PASSWORD", "TRIAL_PASSWORD"):
            saved = self.demo[name]
            self.demo[name] = "invalid'password"
            result = self.run_mode()
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("invalid'password", result.stderr)
            self.demo[name] = saved

    def test_independent_credentials_required(self) -> None:
        self.demo["MYSQL_ROOT_PASSWORD"] = self.demo["TRIAL_PASSWORD"]
        self.assertNotEqual(self.run_mode().returncode, 0)


if __name__ == "__main__":
    unittest.main()
