"""Render real Compose files; verify local/external/off without starting containers."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]


class TrialComposeTests(unittest.TestCase):
    def render(self, trial: str, host: str = "trial-mysql", overlay: bool = False, root: bool = False) -> dict:
        # These are disposable test strings, never production credentials.
        config = "\n".join([
            "POSTGRES_PASSWORD=test-only-postgres", "RABBITMQ_DEFAULT_PASS=test-only-rabbit",
            "SQLCHAT_ENCRYPT_KEY=" + "c" * 32, "SQLCHAT_BOOTSTRAP_PASSWORD=test-only-admin",
            "SQLCHAT_IMAGE_TAG=" + "0" * 40,
            f"SQLCHAT_TRIAL_ENABLED={trial}", f"SQLCHAT_TRIAL_BUILTIN_HOST={host}",
            "SQLCHAT_TRIAL_BUILTIN_USERNAME=sqlchat_demo",
            "SQLCHAT_TRIAL_BUILTIN_PASSWORD=" + "a" * 48,
            "SQLCHAT_TRIAL_MYSQL_ROOT_PASSWORD=" + "b" * 48,
        ])
        process_env = {key: value for key, value in os.environ.items()
                       if not key.startswith(("SQLCHAT_", "POSTGRES_", "RABBITMQ_", "COMPOSE_"))}
        with tempfile.TemporaryDirectory(prefix="sqlchat-compose-test-") as directory:
            env_path = Path(directory) / "test.env"
            env_path.write_text(config, encoding="utf-8")
            command = ["docker", "compose", "-p", "sqlchat-config-test",
                       "-f", str(DEPLOY.parent / "docker-compose.yml" if root else DEPLOY / "docker-compose.prod.yml"), "--env-file", str(env_path)]
            if root and overlay:
                command += ["--profile", "trial-demo"]
            elif overlay:
                command += ["-f", str(DEPLOY / "docker-compose.trial.yml"), "--profile", "trial-demo"]
            result = subprocess.run(command + ["config", "--format", "json"], env=process_env,
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_off_excludes_demo_and_preserves_application_dependencies(self) -> None:
        document = self.render("false")
        self.assertNotIn("trial-mysql", document["services"])
        self.assertNotIn("trial-mysql", document["services"]["api"]["depends_on"])
        self.assertIn("postgres", document["services"]["api"]["depends_on"])

    def test_local_includes_private_capped_demo_and_health_dependency(self) -> None:
        document = self.render("true", overlay=True)
        demo = document["services"]["trial-mysql"]
        self.assertEqual(int(demo["mem_limit"]), 256 * 1024 * 1024)
        self.assertEqual(demo["memswap_limit"], demo["mem_limit"])
        self.assertNotIn("ports", demo)
        self.assertEqual(set(demo["networks"]), {"backend"})
        self.assertEqual(demo["image"], "mysql:8.4")
        self.assertEqual(demo["environment"]["MYSQL_ROOT_HOST"], "localhost")
        self.assertIn("--character-set-server=utf8mb4", demo["command"])
        self.assertEqual(demo["healthcheck"]["test"], ["CMD", "bash", "/opt/sqlchat-healthcheck.sh"])
        self.assertTrue(any(volume.get("target") == "/opt/sqlchat-seed.sql" for volume in demo["volumes"]))
        self.assertTrue(any(volume.get("source") == "trial_mysql_blog_v2_data" for volume in demo["volumes"]))
        for service in ("api", "worker"):
            self.assertEqual(document["services"][service]["depends_on"]["trial-mysql"]["condition"],
                             "service_healthy")
            self.assertNotIn("SQLCHAT_TRIAL_MYSQL_ROOT_PASSWORD", document["services"][service]["environment"])
            self.assertIn("postgres", document["services"][service]["depends_on"])
        decision = subprocess.run([sys.executable, "-B", str(DEPLOY / "trial-mode.py")],
                                  input=json.dumps(document), capture_output=True, text=True, check=False)
        self.assertEqual((decision.returncode, decision.stdout.strip()), (0, "local"), decision.stderr)

    def test_root_profile_reuses_blog_volume_and_private_alias(self) -> None:
        off = self.render("false", root=True)
        self.assertNotIn("trial-mysql", off["services"])
        local = self.render("true", host="sqlchat-demo-mysql", overlay=True, root=True)
        demo = local["services"]["trial-mysql"]
        self.assertEqual(demo["networks"]["backend"]["aliases"], ["sqlchat-demo-mysql"])
        self.assertNotIn("ports", demo)
        self.assertTrue(any(volume.get("source") == "trial_mysql_blog_v2_data" for volume in demo["volumes"]))
        self.assertEqual(demo["healthcheck"]["test"], ["CMD", "bash", "/opt/sqlchat-healthcheck.sh"])


    def test_server_release_transfers_every_required_init_asset(self) -> None:
        workflow = (DEPLOY.parent / ".github/workflows/publish-and-deploy.yml").read_text(encoding="utf-8")
        startup = (DEPLOY / "deploy-on-server.sh").read_text(encoding="utf-8")
        scp_assets = next(line for line in workflow.splitlines() if "deploy/trial-mysql/10-demo.sh deploy/" in line)
        for asset in ("10-demo.sh", "demo.sql", "seed.sql", "healthcheck.sh"):
            self.assertIn("test -f deploy/trial-mysql/" + asset, workflow)
            self.assertIn("deploy/trial-mysql/" + asset, scp_assets)
            self.assertIn("trial-mysql/" + asset, startup)


    def test_external_trial_does_not_enable_local_profile(self) -> None:
        document = self.render("true", host="mysql.example.test")
        self.assertNotIn("trial-mysql", document["services"])
        decision = subprocess.run([sys.executable, "-B", str(DEPLOY / "trial-mode.py")],
                                  input=json.dumps(document), capture_output=True, text=True, check=False)
        self.assertEqual((decision.returncode, decision.stdout.strip()), (0, "external"), decision.stderr)


if __name__ == "__main__":
    unittest.main()
