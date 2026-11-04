"""Public commitment, filesystem scalar and activation-pattern regressions."""

import json
import posixpath
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
import yaml
from artifact_helpers import index_at, tar_files
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.artifact import artifact_name
from ai_skills_engine.artifacts.materialize import materialize
from ai_skills_engine.artifacts.references import rewrite_fields
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.selection.load import load_inputs
from ai_skills_engine.semver_advice import recommend_semver

pytest_plugins = ["artifact_helpers"]


@pytest.mark.parametrize("flag", ["--check", "--check-inputs"])
@pytest.mark.parametrize(
    "change",
    ["lf", "crlf", "missing", "malformed", "duplicate", "format", "digest", "utf8"],
)
def test_public_commitment_byte_equality(
    artifact_repo: Path,
    capsys: pytest.CaptureFixture[str],
    flag: str,
    change: str,
) -> None:
    """Both public gates reject noncanonical/malformed bytes without rewriting."""
    args = ["--repo-root", str(artifact_repo), "build"]
    assert_that(cli.main([*args, "--write-digests"])).is_zero()
    path = artifact_repo / "artifact-digests.json"
    canonical = path.read_bytes()
    mutations = {
        "lf": canonical,
        "crlf": canonical.replace(b"\n", b"\r\n"),
        "malformed": b"{",
        "duplicate": canonical.replace(
            b'"artifactFormat": 1', b'"artifactFormat": 1, "artifactFormat": 1'
        ),
        "format": canonical.replace(b'"artifactFormat": 1', b'"artifactFormat": 9'),
        "digest": canonical.replace(b"sha256:", b"sha255:", 1),
        "utf8": b"\xff",
    }
    if change == "missing":
        path.unlink()
    else:
        path.write_bytes(mutations[change])
    assert_that(cli.main([*args, flag])).is_equal_to(0 if change == "lf" else 1)
    if change == "missing":
        assert_that(path.exists()).is_false()
    else:
        assert_that(path.read_bytes()).is_equal_to(mutations[change])
    if change == "crlf":
        assert_that(capsys.readouterr().err).contains("rebuilt artifact digests")


@pytest.mark.parametrize("owner", ["capability", "projected-resource"])
@pytest.mark.parametrize("kind", ["json", "yaml", "frontmatter"])
@pytest.mark.parametrize(
    "filename",
    [
        "input.txt",
        "input data.txt",
        "input%20data.txt",
        "input#data.txt",
        "input?data.txt",
        "input\U0001f600.txt",
    ],
    ids=["ordinary", "space", "percent", "hash", "question", "emoji"],
)
def test_public_scalar_opens_copied_resource(
    artifact_repo: Path, tmp_path: Path, owner: str, kind: str, filename: str
) -> None:
    """Declared filesystem scalars open actual tar payloads with literal spelling."""
    target = artifact_repo / "shared/data" / filename
    target.write_bytes(b"Literal filesystem resource.\n")
    # A URL-decoded interpretation must not accidentally select this decoy.
    if "%" in filename:
        (target.parent / "input data.txt").write_bytes(b"Wrong decoded resource.\n")
    skill = artifact_repo / "skills/start/SKILL.md"
    skill.write_text("---\nname: start\ndescription: Scalar fixture.\n---\n# Start\n")
    (skill.parent / "config.json").unlink()
    manifest = artifact_repo / "ai-skills.yaml"
    document = read_document(manifest)
    package = document["packages"][0]
    resource_owned = owner == "projected-resource"
    base = artifact_repo / ("shared" if resource_owned else "skills/start")
    filename_config = {
        "json": "config.json",
        "yaml": "config.yaml",
        "frontmatter": "config.md",
    }[kind]
    raw = ("data/" if resource_owned else "../../shared/data/") + filename
    config = base / filename_config
    fields = {"script": raw}
    text = (
        json.dumps(fields, ensure_ascii=False)
        if kind == "json"
        else yaml.safe_dump(fields)
    )
    if kind == "frontmatter":
        text = "---\n" + text + "---\n# Configuration\n"
    config.write_text(text)
    declaration = {filename_config: ["/script"]}
    if resource_owned:
        resources = package.pop("resources")
        resources[0]["x-resource-paths"] = declaration
        package["artifactResources"] = {
            "version": 1,
            "resources": resources,
            "bindings": {"skill/start": ["shared"], "skill/peer": ["shared"]},
        }
        for capability in package["capabilities"]:
            capability.pop("resources")
            capability.pop("x-resource-paths", None)
    else:
        package["capabilities"][0]["x-resource-paths"] = declaration
    manifest.write_text(dump_document(document))
    args = ["--repo-root", str(artifact_repo), "build"]
    assert_that(cli.main([*args, "--write-digests"])).is_zero()
    output = artifact_repo / "dist/artifacts"
    cap = next(
        item
        for item in index_at(output)["packages"][0]["capabilities"]
        if item["id"].endswith("/start")
    )
    files = tar_files(output / artifact_name("fixture/tools"))
    prefix = cap["path"] + "/"
    relative = ("_shared/fixture/shared/" if resource_owned else "") + filename_config
    emitted = files[prefix + relative][0].decode()
    parsed = yaml.safe_load(
        emitted.split("---")[1] if kind == "frontmatter" else emitted
    )
    if kind == "json":
        assert_that(json.loads(emitted)["script"]).is_equal_to(parsed["script"])
    assert_that(parsed["script"]).ends_with("/" + filename)
    member = posixpath.normpath(
        prefix + posixpath.dirname(relative) + "/" + parsed["script"]
    )
    assert_that(member in files).is_true()
    assert_that(files[member][0]).is_equal_to(target.read_bytes())
    exploded = tmp_path / "exploded"
    for name, (data, _mode) in files.items():
        if name.startswith(prefix):
            path = exploded / name.removeprefix(prefix)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    assert_that(
        ((exploded / relative).parent / parsed["script"]).read_bytes()
    ).is_equal_to(target.read_bytes())
    assert_that(cap["portability"]).is_empty()
    assert_that(config.read_text()).is_equal_to(text)
    assert_that(cli.main([*args, "--check"])).is_zero()
    assert_that(cli.main([*args, "--check-inputs"])).is_zero()


def test_public_markdown_keeps_url_serialization(artifact_repo: Path) -> None:
    """Markdown encodes literal filename bytes and retains URL query/fragment."""
    filename = "input data%#?.txt"
    (artifact_repo / "skills/start/config.json").write_text(
        json.dumps({"script": "../../shared/scripts/run.py"})
    )
    (artifact_repo / "shared/data" / filename).write_text("URL resource.\n")
    destination = "../../shared/data/" + quote(filename) + "?mode=read#sample"
    skill = artifact_repo / "skills/start/SKILL.md"
    skill.write_text(
        "---\nname: start\ndescription: URL fixture.\n---\n"
        f"[Data](<{destination}>)\n"
    )
    assert_that(cli.main(["--repo-root", str(artifact_repo), "build"])).is_zero()
    output = artifact_repo / "dist/artifacts"
    files = tar_files(output / artifact_name("fixture/tools"))
    cap = next(
        item
        for item in index_at(output)["packages"][0]["capabilities"]
        if item["id"].endswith("/start")
    )
    assert_that(files[cap["path"] + "/SKILL.md"][0].decode()).contains(
        "<_shared/fixture/shared/data/" + quote(filename) + "?mode=read#sample>"
    )
    assert_that(cap["portability"]).is_empty()


@pytest.mark.parametrize(
    "raw",
    [
        "../../undeclared.txt",
        "../missing.txt",
        "../../shared/data/input%2Etxt",
        "../../shared/data/input.txt#missing",
        "../../shared/data/input.txt?missing",
        "..\\..\\shared\\data\\input.txt",
        "../../shared/data/input.txt\0",
        "javascript:alert(1)",
    ],
    ids=[
        "outside",
        "missing",
        "no-decode",
        "literal-hash",
        "literal-question",
        "backslash",
        "nul",
        "unsafe-scheme",
    ],
)
def test_public_scalar_safety_diagnostics(artifact_repo: Path, raw: str) -> None:
    """Missing, undeclared and unsafe scalar operands never become portable."""
    (artifact_repo / "undeclared.txt").write_text("Outside required closure.\n")
    (artifact_repo / "skills/start/config.json").write_text(json.dumps({"script": raw}))
    assert_that(cli.main(["--repo-root", str(artifact_repo), "build"])).is_zero()
    output = artifact_repo / "dist/artifacts"
    cap = next(
        item
        for item in index_at(output)["packages"][0]["capabilities"]
        if item["id"].endswith("/start")
    )
    files = tar_files(output / artifact_name("fixture/tools"))
    assert_that(
        json.loads(files[cap["path"] + "/config.json"][0])["script"]
    ).is_equal_to(raw)
    assert_that({item["mode"] for item in cap["portability"]}).is_equal_to(
        {"user-explode", "repo-materialize"}
    )
    assert_that("\n".join(item["reason"] for item in cap["portability"])).contains(
        "config.json:"
    )


@pytest.mark.parametrize("key", ["paths", "globs"])
@pytest.mark.parametrize(
    ("old", "new", "level"),
    [
        ("src/{app,lib}/**", "lib}/**", "major"),
        ("src/{app,lib}/**", "src/{app,lib}/**", "none"),
        ("src/{app,lib}/**", "src/**", "major"),
        ("src/app lib/**", "lib/**", "major"),
        ("src/**,tests/**", "tests/**", "major"),
        (["src/**", "tests/**"], ["src/**"], "patch"),
        (["src/**"], ["src/**", "tests/**"], "major"),
        (["src/{app,lib}/**", "tests/**"], ["src/{app,lib}/**"], "patch"),
        (["src/**"], ["src/**"], "none"),
        (["src/**"], None, "major"),
        (None, ["src/**"], "patch"),
    ],
    ids=[
        "brace-fragment",
        "brace-same",
        "ordinary-change",
        "space-fragment",
        "comma-fragment",
        "list-narrow",
        "list-widen",
        "list-brace-narrow",
        "list-same",
        "remove-restriction",
        "add-restriction",
    ],
)
def test_public_resolved_activation_advice(
    artifact_repo: Path, key: str, old: object, new: object, level: str
) -> None:
    """Actual inventories and public indexes preserve whole activation patterns."""
    source = artifact_repo / "skills/start/SKILL.md"
    original = source.read_text()
    indexes: list[dict[str, Any]] = []
    for value in (old, new):
        declaration = "" if value is None else yaml.safe_dump({key: value})
        source.write_text(
            original.replace("\n---\n# Start", "\n" + declaration + "---\n# Start")
        )
        assert_that(cli.main(["--repo-root", str(artifact_repo), "build"])).is_zero()
        index = index_at(artifact_repo / "dist/artifacts")
        cap = next(
            item
            for item in index["packages"][0]["capabilities"]
            if item["id"].endswith("/start")
        )
        attributes = [item for item in cap["hostAttributes"] if item["key"] == key]
        if value is None:
            assert_that(attributes).is_empty()
        else:
            assert_that(attributes).is_length(1)
            assert_that(attributes[0]["value"]).is_equal_to(value)
            assert_that(attributes[0]["semantics"]).is_equal_to("activation")
        indexes.append(index)
    result = recommend_semver(*indexes)
    assert_that(result.level).is_equal_to(level)
    if level == "major":
        assert_that("\n".join(result.reasons)).contains("Widened " + key)


@pytest.mark.parametrize("kind", ["json", "yaml", "frontmatter"])
@pytest.mark.parametrize(
    "value",
    [
        "a\U0001f600.md",
        "a\x85b.md",
        "a\u2028b.md",
        "a\u2029b.md",
        "a\x7fb.md",
        "a\x9bb.md",
        "a\tb.md",
    ],
    ids=["emoji", "nel", "line-separator", "paragraph-separator", "del", "c1", "tab"],
)
def test_rewritten_scalar_reparses_exactly(kind: str, value: str) -> None:
    """Replacement scalars reparse as the exact string in YAML and JSON."""
    document = '{"script": "old.md"}' if kind == "json" else "script: old.md\n"
    if kind == "frontmatter":
        document = "---\n" + document + "---\n# Body\n"
    edited = rewrite_fields(
        text=document,
        pointers=("/script",),
        markdown=kind == "frontmatter",
        replace=lambda _raw: value,
    )
    source = edited.split("---")[1] if kind == "frontmatter" else edited
    assert_that(yaml.safe_load(source)["script"]).is_equal_to(value)
    if kind == "json":
        assert_that(json.loads(edited)["script"]).is_equal_to(value)
    assert_that(
        [character for character in edited if character in "\x85\x9b\u2028\u2029\x7f"]
    ).is_empty()


@pytest.mark.parametrize("change", ["unchanged", "bytes", "mode"])
def test_contained_resource_payload_is_authenticated(
    artifact_repo: Path, change: str
) -> None:
    """A contained resource's own payload record must match the copied bytes."""
    data = artifact_repo / "skills/start/data"
    data.mkdir()
    local = data / "local.txt"
    local.write_text("Inventoried bytes.\n")
    manifest = artifact_repo / "ai-skills.yaml"
    document = read_document(manifest)
    package = document["packages"][0]
    package["resources"].append({"id": "local", "path": "skills/start/data"})
    package["capabilities"][0]["resources"].append("fixture/tools:resource/local")
    manifest.write_text(dump_document(document))
    earlier, _selection = load_inputs(artifact_repo, vendor_roots=None)
    if change == "bytes":
        local.write_text("Changed after the resource was inventoried.\n")
    elif change == "mode":
        local.chmod(0o755)
    current, _selection = load_inputs(artifact_repo, vendor_roots=None)
    capability = next(
        item for item in current.capabilities if str(item.id).endswith("/start")
    )
    resources = {str(item.id): item for item in earlier.resources}
    required = (
        (resources["fixture/tools:resource/local"], data),
        (resources["fixture/tools:resource/shared"], artifact_repo / "shared"),
    )
    if change != "unchanged":
        with pytest.raises(ValueError, match="Source changed during artifact build"):
            materialize(
                capability=capability,
                source=artifact_repo / "skills/start",
                resources=required,
            )
        return
    files, records, _portability = materialize(
        capability=capability, source=artifact_repo / "skills/start", resources=required
    )
    assert_that([item["path"] for item in records]).contains(
        "data", "_shared/fixture/shared"
    )
    assert_that(files["data/local.txt"][0]).is_equal_to(local.read_bytes())
    assert_that(files).contains_key("_shared/fixture/shared/data/input.txt")
