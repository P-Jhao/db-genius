"""Validate rendered Compose configuration without sourcing shell environment files."""

import json
import re
import sys


def required(env: dict[str, str], name: str) -> str:
    value = str(env.get(name, "")).strip()
    if not value:
        raise ValueError(f"Set {name} before enabling trial mode")
    return value


def main() -> None:
    services = json.load(sys.stdin)["services"]
    env = services["api"]["environment"]
    enabled = str(env["SQLCHAT_TRIAL_ENABLED"]).lower()
    if enabled not in {"true", "false"}:
        raise ValueError("SQLCHAT_TRIAL_ENABLED must be exactly true or false")
    if enabled == "false":
        print("off")
        return
    for suffix in ("DB_NAME", "HOST", "PORT", "USERNAME", "PASSWORD"):
        required(env, f"SQLCHAT_TRIAL_BUILTIN_{suffix}")
    if env["SQLCHAT_TRIAL_BUILTIN_HOST"] != "trial-mysql":
        print("external")
        return
    if str(env["SQLCHAT_TRIAL_BUILTIN_PORT"]) != "3306":
        raise ValueError("Local trial MySQL must use port 3306")
    for suffix in ("DB_NAME", "USERNAME"):
        value = env[f"SQLCHAT_TRIAL_BUILTIN_{suffix}"]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", value):
            raise ValueError(f"Invalid local trial {suffix}: use ASCII letters/digits/_/-")
    if env["SQLCHAT_TRIAL_BUILTIN_USERNAME"].lower() == "root":
        raise ValueError("The trial application account cannot be root")
    demo_env = services["trial-mysql"]["environment"]
    for name in ("MYSQL_ROOT_PASSWORD", "TRIAL_PASSWORD"):
        if not re.fullmatch(r"[0-9a-fA-F]{32,64}", str(demo_env.get(name, ""))):
            raise ValueError(f"Local demo {name} must contain 32-64 hexadecimal characters; use openssl rand -hex 24")
    if demo_env["MYSQL_ROOT_PASSWORD"] == demo_env["TRIAL_PASSWORD"]:
        raise ValueError("Use independent root and read-only trial passwords")
    print("local")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError) as exc:
        sys.exit(str(exc))
