"""Read-only v2 demo oracle; validates exact owned Compose container before exec."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(command: list[str], *, stdin: str | None = None) -> str:
    result = subprocess.run(command, input=stdin, text=True, encoding="utf-8", capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Demo verification command failed; inspect container privately")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", required=True, help="Exact container ID supplied by operator")
    parser.add_argument("--project", default="sqlchat")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if len(args.container) != 64 or any(char not in "0123456789abcdef" for char in args.container):
        raise ValueError("A full lowercase container ID is required")
    info = json.loads(run(["docker", "inspect", args.container]))[0]
    labels = info["Config"]["Labels"]
    if labels.get("com.docker.compose.project") != args.project or labels.get("com.docker.compose.service") != "trial-mysql":
        raise ValueError("Refusing container outside the exact trial-mysql project")
    if not any(mount.get("Name", "").endswith("_trial_mysql_blog_v2_data") for mount in info["Mounts"]):
        raise ValueError("Demo is not using the new versioned volume")
    def query(sql: str) -> list[list[str]]:
        # Password stays inside the container, never in process argv or output.
        shell = 'export MYSQL_PWD="$TRIAL_PASSWORD"; exec mysql --default-character-set=utf8mb4 --protocol=TCP -h 127.0.0.1 -u "$TRIAL_USERNAME" -D "$TRIAL_DATABASE" --batch --raw'
        output = run(["docker", "exec", "-i", args.container, "bash", "-c", shell], stdin=sql)
        return [line.split("\t") for line in output.splitlines()]
    schemas = query("SELECT table_name,column_name,column_comment FROM information_schema.columns WHERE table_schema=DATABASE() ORDER BY table_name,ordinal_position;")
    if len({row[0] for row in schemas[1:]}) != 10 or not all(row[2] for row in schemas[1:]):
        raise AssertionError("Expected ten tables with comments on every column")
    if not any("用户" in row[2] for row in schemas[1:]):
        raise AssertionError("Chinese column comments were not preserved")
    cases = json.loads((ROOT / "deploy/trial-mysql/oracle.json").read_text(encoding="utf-8"))
    report = {"tableCount": 10, "columnCount": len(schemas)-1, "commentsUtf8": True, "cases": []}
    for case in cases:
        rows = query(case["sql"] + ";")
        expected = [[str(value) for value in record.values()] for record in case["expected"]]
        if rows[1:] != expected:
            raise AssertionError("Oracle mismatch: " + case["id"])
        report["cases"].append({"id": case["id"], "passed": True, "rowCount": len(expected)})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Readonly MySQL oracle passed; report saved")


if __name__ == "__main__":
    main()
