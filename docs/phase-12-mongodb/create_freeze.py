"""Read-only accepted archive comparison and one-time inventory creation."""

import ast
import difflib
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

OWNED = [
    "backend/app/adapters/diagnostics.py", "backend/app/adapters/mongodb.py",
    "backend/app/adapters/mongodb_command.py", "backend/app/adapters/mongodb_metadata.py",
    "backend/app/adapters/types.py", "backend/app/adapters/registry.py", "backend/app/adapters/document.py",
    "backend/app/services/db_config_common.py", "backend/app/services/db_config.py",
    "backend/app/agent/workflow_mongodb.py", "backend/app/agent/workflow.py",
    "backend/app/agent/workflow_schema.py", "backend/app/agent/workflow_rows.py",
    "backend/tests/test_mongodb_adapter.py", "backend/tests/test_mongodb_config.py",
    "backend/tests/test_mongodb_credentials.py", "backend/tests/test_mongodb_document.py",
    "backend/tests/test_mongodb_workflow.py", "backend/tests/test_mongodb_metadata.py",
    "backend/tests/test_mongodb_integration.py", "backend/tests/test_mongodb_interruptions.py",
    "backend/tests/test_mongodb_workflow_integration.py", "backend/tests/test_mongodb_diagnostics.py",
    "backend/tests/test_mysql_family.py", "backend/tests/test_mysql_family_outcomes.py",
    "backend/tests/test_mysql_family_workflow.py",
]


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def entry(root: Path, name: str) -> dict[str, object]:
    data = (root / name).read_bytes()
    return {"path": name, "bytes": len(data), "sha256": digest(data)}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verify_history(root: Path, folder: str, manifest: str, expected: str) -> dict[str, object]:
    previous = root.parent / folder
    path = previous / "docs/phase-12-mongodb" / manifest
    if digest(path.read_bytes()) != expected:
        raise AssertionError("Historical Mongo inventory changed")
    files = json.loads(path.read_text(encoding="utf-8"))["files"]
    for item in files:
        if entry(previous, item["path"]) != item:
            raise AssertionError(f"Historical frozen file changed: {item['path']}")
    return {"inventorySha256": expected, "filesVerified": len(files)}


def function_text(source: str, name: str) -> str:
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(source, node)
            if segment is None:
                raise ValueError("Function source is missing")
            return segment
    raise ValueError(f"Function {name} is missing")


def run() -> None:
    root = Path(__file__).resolve().parents[2]
    docs = root / "docs/phase-12-mongodb"
    destination = docs / "final-freeze.json"
    if destination.exists():
        raise FileExistsError("Mongo inventory is already frozen")
    baseline = json.loads((root / "BASELINE.json").read_text(encoding="utf-8"))
    archived = subprocess.run(["git", "archive", "--format=zip", baseline["baseCommit"]],
                              cwd=root.parents[2], capture_output=True, check=True).stdout
    with zipfile.ZipFile(io.BytesIO(archived)) as archive:
        accepted = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    changed = []
    guards = []
    unchanged = []
    for name, data in sorted(accepted.items()):
        current = (root / name).read_bytes()
        if current != data:
            if name not in OWNED:
                raise AssertionError(f"Unowned accepted file changed: {name}")
            changed.append(name)
        else:
            unchanged.append(name)
            if name.startswith("backend/app/") or name == "AGENTS.md":
                guards.append(entry(root, name))
    for name in OWNED:
        if name not in accepted:
            changed.append(name)
        if len((root / name).read_text(encoding="utf-8").splitlines()) > 300:
            raise AssertionError(f"Owned file exceeds 300 lines: {name}")
    patch: list[str] = []
    for name in sorted(changed):
        before = accepted[name].decode("utf-8").replace("\r\n", "\n").splitlines(
            keepends=True,
        ) if name in accepted else []
        after = (root / name).read_text(encoding="utf-8").splitlines(keepends=True)
        patch.extend(difflib.unified_diff(before, after, fromfile="a/" + name, tofile="b/" + name))
    (docs / "public-diff.patch").write_text("".join(patch), encoding="utf-8")
    historical = [verify_history(root, "s12-mongodb-5e62b18039844ad09339c0e6cb4b83bb",
                                "preparation-files.json",
                                "759c60639b7f47571ba6e9ed5126ec1e9a319c4c5e6345d4758f0a297ebcf9eb"),
                  verify_history(root, "s12-mongodb-revision-0e265b8e640244cc91ce963ccec10630",
                                 "revision-freeze.json",
                                 "9a26ff8879f06069f6f30391b28c429164783ca0bf530cd477189b812eca0138")]
    previous = root.parent / "s12-mongodb-integrated-3850c792c948438aae612f79ee3c1188"
    real_evidence = json.loads((docs / "real-mongo-integrated.json").read_text(encoding="utf-8"))
    reuse = []
    for name, old_sha in real_evidence["codeSha256"].items():
        before, after = (previous / name).read_bytes(), (root / name).read_bytes()
        if digest(before) != old_sha:
            raise AssertionError("Prior actual Mongo code evidence changed")
        same_text = before.decode("utf-8").splitlines() == after.decode("utf-8").splitlines()
        if name != "backend/app/adapters/mongodb.py" and not same_text:
            raise AssertionError(f"Actual Mongo evidence source changed beyond diagnosis: {name}")
        reuse.append({"path": name, "oldSha256": old_sha, "finalSha256": digest(after),
                      "bytesEqual": before == after, "normalizedLineEndingsEqual": same_text})
    config_path = "backend/app/services/db_config.py"
    before_doc = function_text(accepted[config_path].decode("utf-8").replace("\r\n", "\n"), "generate_doc")
    after_doc = function_text((root / config_path).read_text(encoding="utf-8"), "generate_doc")
    if before_doc != after_doc:
        raise AssertionError("Accepted S05 manual document path changed")
    write_json(docs / "evidence-reuse.json", {
        "realMongoPriorPassed": 20, "priorBase": real_evidence["baseCommit"],
        "finalBase": baseline["baseCommit"], "sourceComparisons": reuse,
        "laterFaultPathChange": "Mongo diagnostic redaction only; 91 targeted tests passed",
        "actualMongoRerunClaimed": False, "historicalFrozenInventories": historical,
        "generateDocPreservedSha256": digest(after_doc.encode()),
    })
    delivered = sorted(changed + [str(path.relative_to(root)).replace("\\", "/")
                                 for path in docs.iterdir() if path.is_file() and path != destination])
    if len(delivered) != len(set(delivered)):
        raise AssertionError("Duplicate delivered path")
    write_json(destination, {
        "kind": "S12 Mongo production minimal integration final freeze",
        "baseCommit": baseline["baseCommit"], "laterAcceptedDocsOnlyHead": "ecb011f",
        "files": [entry(root, name) for name in delivered], "codeAndTestFileCount": len(changed),
        "preservedBackendGuards": guards, "preservedAcceptedFileCount": len(unchanged),
        "preservedAcceptedTreeSha256": digest("\n".join(name + ":" + digest(accepted[name])
                                                        for name in unchanged).encode()),
        "legacyInventories": historical, "generateDocPreservedSha256": digest(after_doc.encode()),
        "noGitMutation": True, "noSharedWorkspaceWrite": True, "realModelEffectsTested": False,
    })
    print(json.dumps({"manifest": str(destination), "sha256": digest(destination.read_bytes()),
                      "files": len(delivered), "codeAndTests": len(changed), "guards": len(guards)}, indent=2))


if __name__ == "__main__":
    run()
