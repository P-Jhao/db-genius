"""Operator-reviewed local demo dotenv upgrade; never outputs dotenv values."""
import argparse
import re
import secrets
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply approved private dotenv changes")
    args = parser.parse_args()
    path = ROOT / ".env"
    values = dotenv_values(path)
    if values.get("SQLCHAT_TRIAL_ENABLED", "").lower() != "true":
        raise ValueError("Local demo upgrade requires enabled trial mode")
    if values.get("SQLCHAT_TRIAL_BUILTIN_HOST") != "sqlchat-demo-mysql":
        raise ValueError("Unexpected demo host; refusing private dotenv modification")
    username = values.get("SQLCHAT_TRIAL_BUILTIN_USERNAME", "")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", username) or username.lower() == "root":
        raise ValueError("Demo must use a valid non-root readonly account")
    profiles = values.get("COMPOSE_PROFILES", "")
    if profiles not in (None, "", "trial-demo"):
        raise ValueError("Unexpected existing profiles; review manually")
    updates = {"COMPOSE_PROFILES": "trial-demo", "SQLCHAT_TRIAL_BUILTIN_PORT": "3306",
               "SQLCHAT_TRIAL_BUILTIN_DB_NAME": "sqlchat_blog_demo"}
    password = values.get("SQLCHAT_TRIAL_BUILTIN_PASSWORD", "")
    if not re.fullmatch(r"[0-9a-fA-F]{32,64}", password):
        updates["SQLCHAT_TRIAL_BUILTIN_PASSWORD"] = secrets.token_hex(24)
    if not values.get("SQLCHAT_TRIAL_MYSQL_ROOT_PASSWORD"):
        updates["SQLCHAT_TRIAL_MYSQL_ROOT_PASSWORD"] = secrets.token_hex(24)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for key, value in updates.items():
        indices = [index for index, line in enumerate(lines) if line.startswith(key + "=")]
        if len(indices) > 1:
            raise ValueError("Duplicate managed dotenv key: " + key)
        if indices:
            lines[indices[0]] = key + "=" + value
        else:
            lines.append(key + "=" + value)
    if args.apply:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Applied keys: " if args.apply else "Proposed keys: ", ", ".join(sorted(updates)))


if __name__ == "__main__":
    main()
