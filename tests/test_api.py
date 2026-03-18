"""API server endpoint tests."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from core.api_server import create_app


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
