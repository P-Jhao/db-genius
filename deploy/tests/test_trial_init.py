"""Exercise executable and sourced MySQL init paths without a database."""
import subprocess
import unittest
from pathlib import Path

INIT = Path(__file__).resolve().parents[1] / "trial-mysql/10-demo.sh"


class TrialInitTests(unittest.TestCase):
    def verify(self, sourced: bool) -> None:
        source = INIT.read_text(encoding="utf-8")
        self.assertNotIn("\r", INIT.read_bytes().decode("utf-8"))
        source = source.replace("/usr/local/bin/docker-entrypoint.sh", "$fixture_dir/entrypoint.sh")
        source = source.replace("/opt/sqlchat-demo.sql", "/dev/null").replace("/opt/sqlchat-seed.sql", "/dev/null")
        script = r'''
set -eo pipefail
fixture_dir=$(mktemp -d)
trap 'rm -rf "$fixture_dir"' EXIT
export fixture_dir
export TRIAL_DATABASE=sqlchat_blog_demo TRIAL_USERNAME=sqlchat_demo
export TRIAL_PASSWORD=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
cat > "$fixture_dir/entrypoint.sh" <<'ENTRYPOINT'
docker_process_sql() { cat >/dev/null; echo sql-call >> "$fixture_dir/calls"; }
mysql_get_config() { echo /tmp/mysql-fixture.sock; }
main() { echo 'Unexpected recursive entrypoint' >&2; exit 99; }
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main; fi
ENTRYPOINT
cat > "$fixture_dir/init.sh" <<'INIT_SCRIPT'
''' + source + '\nINIT_SCRIPT\n'
        script += ('source "$fixture_dir/entrypoint.sh"\nsource "$fixture_dir/init.sh"\n' if sourced
                   else 'bash "$fixture_dir/init.sh"\n')
        script += '[[ "$(wc -l < "$fixture_dir/calls")" == 3 ]]\n'
        result = subprocess.run(["bash", "--noprofile", "--norc"], input=script.encode("utf-8"),
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))

    def test_executable_mount_loads_helpers_without_running_entrypoint_main(self) -> None:
        self.verify(False)

    def test_sourced_mount_uses_existing_helpers(self) -> None:
        self.verify(True)


if __name__ == "__main__":
    unittest.main()
