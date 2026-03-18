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
