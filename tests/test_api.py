"""API server endpoint tests."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from core.api_server import create_app
import modules.import_project.src.import_tools as import_tools_mod


@pytest.fixture(scope="module")
def client():
    app = create_app("configs")
    with TestClient(app) as c:
        yield c


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_tools_list(client):
    res = client.get("/tools")
    assert res.status_code == 200
    assert "tools" in res.json()
    assert isinstance(res.json()["tools"], list)


def test_files_list_roots(client):
    res = client.get("/files")
    assert res.status_code == 200
    entries = res.json()["entries"]
    names = [e["name"] for e in entries]
    assert "workspace" in names


def test_files_list_forbidden_root(client):
    res = client.get("/files?path=configs")
    assert res.status_code == 403


def test_files_write_read_delete(client):
    path = "workspace/_test_api_file.txt"
    # Write
    res = client.post("/files/write", json={"path": path, "content": "hello api"})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    # Read
    res = client.get(f"/files/read?path={path}")
    assert res.status_code == 200
    assert res.json()["content"] == "hello api"
    # Delete
    res = client.post("/files/delete", json={"path": path})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    # Verify gone
    res = client.get(f"/files/read?path={path}")
    assert res.status_code == 404


def test_files_rename(client):
    old_path = "workspace/_test_rename_src.txt"
    new_path = "workspace/_test_rename_dst.txt"
    # Create source
    client.post("/files/write", json={"path": old_path, "content": "rename me"})
    # Rename
    res = client.post("/files/rename", json={"old_path": old_path, "new_path": new_path})
    assert res.status_code == 200
    # Read new path
    res = client.get(f"/files/read?path={new_path}")
    assert res.status_code == 200
    assert res.json()["content"] == "rename me"
    # Old path should be gone
    res = client.get(f"/files/read?path={old_path}")
    assert res.status_code == 404
    # Cleanup
    client.post("/files/delete", json={"path": new_path})


def test_files_rename_forbidden_root(client):
    res = client.post("/files/rename", json={"old_path": "configs/config.toml", "new_path": "workspace/x.toml"})
    assert res.status_code == 403


def test_files_delete_not_found(client):
    res = client.post("/files/delete", json={"path": "workspace/_nonexistent_delete_test.txt"})
    assert res.status_code == 404


def test_roadmap_get(client):
    res = client.get("/roadmap")
    assert res.status_code == 200
    data = res.json()
    assert "milestones" in data
    assert len(data["milestones"]) > 0
    # Each milestone should have tasks
    for m in data["milestones"]:
        assert "tasks" in m


def test_roadmap_patch_task(client):
    # Read roadmap to find a pending task
    res = client.get("/roadmap")
    data = res.json()
    test_task_id = None
    for m in data["milestones"]:
        for t in m["tasks"]:
            if t["status"] == "pending":
                test_task_id = t["id"]
                break
        if test_task_id:
            break
    assert test_task_id is not None, "No pending task found to test"

    # Update to in_progress
    res = client.patch(f"/roadmap/task/{test_task_id}", json={"status": "in_progress"})
    assert res.status_code == 200
    assert res.json()["new_status"] == "in_progress"

    # Verify it changed
    res = client.get("/roadmap")
    data = res.json()
    found = False
    for m in data["milestones"]:
        for t in m["tasks"]:
            if t["id"] == test_task_id:
                assert t["status"] == "in_progress"
                found = True
                break
    assert found

    # Reset back to pending
    res = client.patch(f"/roadmap/task/{test_task_id}", json={"status": "pending"})
    assert res.status_code == 200


def test_roadmap_patch_task_invalid_status(client):
    res = client.patch("/roadmap/task/t1-1", json={"status": "invalid"})
    assert res.status_code == 400


def test_roadmap_patch_task_not_found(client):
    res = client.patch("/roadmap/task/nonexistent-id", json={"status": "done"})
    assert res.status_code == 404


def test_build_detect(client):
    res = client.get("/build/detect?path=workspace")
    assert res.status_code == 200
    data = res.json()
    assert "system" in data
    assert "cwd" in data


def test_build_detect_forbidden(client):
    res = client.get("/build/detect?path=configs")
    assert res.status_code == 403


def test_search_files(client):
    # Create a test file to search
    client.post("/files/write", json={"path": "workspace/_search_test.py", "content": "def hello_world():\n    pass\n"})
    res = client.get("/search?q=hello_world&path=workspace")
    assert res.status_code == 200
    data = res.json()
    assert data["query"] == "hello_world"
    assert data["count"] >= 1
    assert any("hello_world" in r["text"] for r in data["results"])
    # Cleanup
    client.post("/files/delete", json={"path": "workspace/_search_test.py"})


def test_search_files_no_results(client):
    res = client.get("/search?q=zzz_nonexistent_pattern_zzz&path=workspace")
    assert res.status_code == 200
    assert res.json()["count"] == 0


def test_search_files_forbidden_root(client):
    res = client.get("/search?q=test&path=configs")
    assert res.status_code == 403


def test_files_import_normal(client):
    """Importing a plain external directory into workspace/ should succeed."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "my_project"
        src.mkdir()
        (src / "hello.txt").write_text("hello")
        res = client.post(
            "/files/import",
            json={"source_path": str(src), "destination_name": "_test_import_normal"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["files_copied"] >= 1
        # Cleanup
        client.post("/files/delete", json={"path": "workspace/_test_import_normal"})


def test_files_import_self_reference(client, tmp_path):
    """Importing a directory whose destination is inside the source must succeed
    without infinite recursion (the 'copy-into-self' scenario that caused the
    original 400 errors when importing the SwissAgent project itself)."""
    # Build a mini-project whose workspace dir is a sub-directory of the source
    src = tmp_path / "SelfProject"
    src.mkdir()
    (src / "pyproject.toml").write_text('[project]\nname="test"')
    (src / "core").mkdir()
    (src / "core" / "main.py").write_text("# main")
    workspace_in_src = src / "workspace"
    workspace_in_src.mkdir()
    (workspace_in_src / "existing_project").mkdir()

    import modules.import_project.src.import_tools as m
    original_workspace_root = m._workspace_root
    m._workspace_root = lambda: workspace_in_src
    try:
        res = client.post(
            "/files/import",
            json={"source_path": str(src), "destination_name": "SelfProject"},
        )
    finally:
        m._workspace_root = original_workspace_root

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    # The destination must exist but must NOT contain a copy of workspace/ inside
    # it (i.e. no infinite recursion artefact)
    dst = workspace_in_src / "SelfProject"
    assert dst.exists()
    assert not (dst / "workspace").exists(), (
        "workspace/ was copied into itself — the self-reference guard did not work"
    )
    assert (dst / "pyproject.toml").exists()
    assert (dst / "core" / "main.py").exists()


def test_files_import_already_exists_no_overwrite(client):
    """Re-importing without overwrite=true must return 400."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "dup_project"
        src.mkdir()
        (src / "file.txt").write_text("data")
        # First import
        client.post(
            "/files/import",
            json={"source_path": str(src), "destination_name": "_test_import_dup"},
        )
        # Second import without overwrite
        res = client.post(
            "/files/import",
            json={"source_path": str(src), "destination_name": "_test_import_dup"},
        )
        assert res.status_code == 400
        assert "already exists" in res.json()["detail"]
        # Cleanup
        client.post("/files/delete", json={"path": "workspace/_test_import_dup"})


def test_files_import_nonexistent_source(client):
    """Importing a path that does not exist must return 400."""
    res = client.post(
        "/files/import",
        json={"source_path": "/nonexistent/path/to/project"},
    )
    assert res.status_code == 400
    assert "does not exist" in res.json()["detail"]


# ── New endpoint tests ────────────────────────────────────────────────────────

def test_roadmap_next_returns_task(client):
    """GET /roadmap/next must return a task (or null if all done)."""
    res = client.get("/roadmap/next")
    assert res.status_code == 200
    data = res.json()
    assert "task" in data
    assert "milestone" in data
    # If a task exists it must have id, title, status
    if data["task"] is not None:
        assert "id" in data["task"]
        assert "title" in data["task"]
        assert "status" in data["task"]


def test_git_clone_missing_url(client):
    """POST /git/clone with empty url must return 400."""
    res = client.post("/git/clone", json={"url": ""})
    assert res.status_code == 400
    assert "URL is required" in res.json()["detail"]


def test_git_clone_existing_destination(client, tmp_path):
    """POST /git/clone into an already-existing destination must return 400."""
    import shutil
    from pathlib import Path
    base = Path(".")
    dest = Path("projects/_test_clone_exists")
    dest.mkdir(parents=True, exist_ok=True)
    try:
        res = client.post(
            "/git/clone",
            json={"url": "https://github.com/example/repo.git", "destination": "_test_clone_exists"},
        )
        assert res.status_code == 400
        assert "already exists" in res.json()["detail"]
    finally:
        if dest.exists():
            shutil.rmtree(str(dest))


def test_git_clone_invalid_url(client):
    """POST /git/clone with a non-existent remote must return 400."""
    res = client.post(
        "/git/clone",
        json={"url": "https://invalid.invalid/nonexistent/repo.git", "destination": "_test_clone_invalid"},
        timeout=15,
    )
    assert res.status_code in (400, 500)
    # Make sure destination was not left behind
    import shutil
    from pathlib import Path
    dest = Path("projects/_test_clone_invalid")
    if dest.exists():
        shutil.rmtree(str(dest))


# ---------------------------------------------------------------------------
# Git panel endpoints
# ---------------------------------------------------------------------------

def test_git_status_not_a_repo(client, tmp_path):
    """GET /git/status on a path without .git returns error key."""
    res = client.get("/git/status?path=workspace")
    assert res.status_code == 200
    data = res.json()
    # Either returns branch info (if workspace is a repo) or error
    assert "branch" in data or "error" in data


def test_git_diff_not_a_repo(client):
    """GET /git/diff on non-repo path."""
    res = client.get("/git/diff?path=workspace")
    assert res.status_code == 200
    data = res.json()
    assert "diff" in data or "error" in data


def test_git_stage_bad_root(client):
    """POST /git/stage with a disallowed root must return 403."""
    res = client.post("/git/stage", json={"path": "etc/passwd", "files": []})
    assert res.status_code == 403


def test_git_commit_bad_root(client):
    """POST /git/commit with a disallowed root must return 403."""
    res = client.post("/git/commit", json={"path": "etc", "message": "test"})
    assert res.status_code == 403


def test_git_commit_empty_message(client):
    """POST /git/commit without a message must return 400."""
    res = client.post("/git/commit", json={"path": "workspace", "message": ""})
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Knowledge endpoints
# ---------------------------------------------------------------------------

def test_knowledge_list_empty(client):
    """GET /knowledge/list returns a sources list."""
    res = client.get("/knowledge/list?project_path=")
    assert res.status_code == 200
    data = res.json()
    assert "sources" in data


def test_knowledge_remove_nonexistent(client):
    """POST /knowledge/remove with unknown source_id should return ok or not_found."""
    res = client.post("/knowledge/remove", json={"source_id": "nonexistent_id_xyz", "project_path": ""})
    assert res.status_code == 200


def test_knowledge_search_returns_results_key(client):
    """GET /knowledge/search always returns a results list."""
    res = client.get("/knowledge/search?query=python&project_path=")
    assert res.status_code == 200
    data = res.json()
    assert "results" in data


# ---------------------------------------------------------------------------
# Profile / Rules endpoints
# ---------------------------------------------------------------------------

def test_profile_get_empty(client):
    """GET /profile returns a profile dict."""
    res = client.get("/profile?project_path=workspace/_test_profile")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict)


def test_profile_set_and_get(client):
    """POST /profile then GET /profile should reflect saved values."""
    import shutil
    from pathlib import Path
    test_path = "workspace/_test_profile_set"
    try:
        res = client.post("/profile", json={
            "project_path": test_path,
            "project_name": "Test Project",
            "tech_stack": ["Python", "FastAPI"],
        })
        assert res.status_code == 200
        data = res.json()
        # Response is {"success": True, "profile": {...}, ...} or similar
        assert data.get("success") is True or "profile" in data or "project_name" in data

        get_res = client.get(f"/profile?project_path={test_path}")
        assert get_res.status_code == 200
    finally:
        p = Path(test_path)
        if p.exists():
            shutil.rmtree(str(p))


def test_rules_get_empty(client):
    """GET /rules returns a rules list."""
    res = client.get("/rules?project_path=workspace/_test_rules")
    assert res.status_code == 200
    data = res.json()
    assert "rules" in data


def test_rules_add_invalid_type(client):
    """POST /rules with invalid rule_type must return 400."""
    res = client.post("/rules", json={"rule": "Do something", "rule_type": "invalid_type"})
    assert res.status_code == 400


def test_rules_add_and_remove(client):
    """Add a rule then remove it by its ID."""
    import shutil
    from pathlib import Path
    test_path = "workspace/_test_rules_add"
    try:
        add_res = client.post("/rules", json={"rule": "Use type hints", "rule_type": "must", "project_path": test_path})
        assert add_res.status_code == 200
        rule_data = add_res.json()
        rule_id = rule_data.get("id") or rule_data.get("rule", {}).get("id")
        if rule_id:
            del_res = client.delete(f"/rules/{rule_id}?project_path={test_path}")
            assert del_res.status_code == 200
    finally:
        p = Path(test_path)
        if p.exists():
            shutil.rmtree(str(p))


# ---------------------------------------------------------------------------
# Scaffold endpoints
# ---------------------------------------------------------------------------

def test_scaffold_module_endpoint(client, tmp_path):
    """POST /scaffold/module creates a module skeleton."""
    import shutil
    from pathlib import Path
    name = "_test_api_scaffold_mod"
    try:
        res = client.post("/scaffold/module", json={"name": name, "description": "Test module via API"})
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "created" or "error" in data  # error if already exists
    finally:
        p = Path("modules") / name
        if p.exists():
            shutil.rmtree(str(p))


def test_scaffold_plugin_endpoint(client, tmp_path):
    """POST /scaffold/plugin creates a plugin skeleton."""
    import shutil
    from pathlib import Path
    name = "_test_api_scaffold_plugin"
    try:
        res = client.post("/scaffold/plugin", json={"name": name, "description": "Test plugin via API"})
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "created" or "error" in data
    finally:
        p = Path("plugins") / name
        if p.exists():
            shutil.rmtree(str(p))


def test_scaffold_tests_endpoint(client, tmp_path):
    """POST /scaffold/tests generates test stubs."""
    res = client.post("/scaffold/tests", json={"module_name": "filesystem"})
    assert res.status_code == 200
    data = res.json()
    # filesystem tests might already exist; that's fine
    assert "status" in data or "error" in data
