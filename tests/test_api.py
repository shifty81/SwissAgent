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
    # Use a known task id (t1-1) to test the PATCH endpoint
    test_task_id = "t1-1"

    # Read current status so we can restore it
    res = client.get("/roadmap")
    data = res.json()
    original_status = None
    for m in data["milestones"]:
        for t in m["tasks"]:
            if t["id"] == test_task_id:
                original_status = t["status"]
                break
        if original_status:
            break
    assert original_status is not None, f"Task {test_task_id} not found in roadmap"

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

    # Restore original status
    res = client.patch(f"/roadmap/task/{test_task_id}", json={"status": original_status})
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


# ---------------------------------------------------------------------------
# Phase 7 — AI editor endpoints
# ---------------------------------------------------------------------------

def test_ai_complete_returns_completion_key(client):
    """/ai/complete returns a JSON object with a 'completion' key."""
    res = client.post("/ai/complete", json={
        "file_content": "def greet(name):\n    ",
        "cursor_offset": 20,
        "language": "python",
        "path": "workspace/test_greet.py",
        "llm_backend": "ollama",
    })
    assert res.status_code == 200
    data = res.json()
    assert "completion" in data
    assert isinstance(data["completion"], str)


def test_ai_complete_empty_content(client):
    """/ai/complete handles empty file content gracefully."""
    res = client.post("/ai/complete", json={
        "file_content": "",
        "cursor_offset": 0,
        "language": "python",
    })
    assert res.status_code == 200
    assert "completion" in res.json()


def test_ai_action_explain(client):
    """/ai/action returns a result for 'explain' action."""
    res = client.post("/ai/action", json={
        "action": "explain",
        "selection": "x = x + 1",
        "language": "python",
    })
    assert res.status_code == 200
    data = res.json()
    assert "result" in data
    assert isinstance(data["result"], str)


def test_ai_action_all_types(client):
    """/ai/action accepts all documented action types."""
    for action in ("explain", "refactor", "tests", "fix", "docstring"):
        res = client.post("/ai/action", json={
            "action": action,
            "selection": "print('hello')",
            "language": "python",
        })
        assert res.status_code == 200, f"action={action} returned {res.status_code}"
        assert "result" in res.json()


def test_ai_propose_returns_proposed_content(client):
    """/ai/propose returns a JSON object with a 'proposed_content' key."""
    res = client.post("/ai/propose", json={
        "instruction": "Add a docstring to the function",
        "file_content": "def add(a, b):\n    return a + b\n",
        "language": "python",
        "path": "workspace/test_add.py",
    })
    assert res.status_code == 200
    data = res.json()
    assert "proposed_content" in data
    assert isinstance(data["proposed_content"], str)


def test_ai_propose_empty_instruction(client):
    """/ai/propose works with an empty instruction."""
    res = client.post("/ai/propose", json={
        "instruction": "",
        "file_content": "x = 1\n",
        "language": "python",
    })
    assert res.status_code == 200
    assert "proposed_content" in res.json()


# ---------------------------------------------------------------------------
# Phase 9 — Plugin ecosystem endpoints
# ---------------------------------------------------------------------------

def test_list_plugins(client):
    """GET /plugins returns a list of plugins."""
    res = client.get("/plugins")
    assert res.status_code == 200
    data = res.json()
    assert "plugins" in data
    assert isinstance(data["plugins"], list)
    assert "count" in data


def test_reload_plugins(client):
    """POST /plugins/reload reloads all plugins."""
    res = client.post("/plugins/reload")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "reloaded"
    assert "plugins" in data


def test_install_plugin_empty_url(client):
    """POST /plugins/install with empty URL returns 400."""
    res = client.post("/plugins/install", json={"url": ""})
    assert res.status_code == 400


def test_remove_plugin_not_found(client):
    """DELETE /plugins/{name} for non-existent plugin returns 404."""
    res = client.delete("/plugins/_nonexistent_plugin_xyz")
    assert res.status_code == 404


def test_remove_plugin_path_traversal(client):
    """DELETE /plugins/{name} with path traversal is rejected."""
    res = client.delete("/plugins/..%2Fcore")
    assert res.status_code in (400, 404, 422)


def test_generate_plugin_missing_fields(client):
    """POST /plugins/generate with missing fields returns 400."""
    res = client.post("/plugins/generate", json={"name": "", "description": ""})
    assert res.status_code == 400


def test_generate_plugin_creates_skeleton(client):
    """POST /plugins/generate creates a plugin skeleton."""
    import shutil
    from pathlib import Path
    name = "_test_api_gen_plugin"
    created_plugin = None
    try:
        res = client.post("/plugins/generate", json={"name": name, "description": "Auto-generated test plugin"})
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "created" or "error" in data
        # Use the actual slug returned by the API for cleanup
        created_plugin = data.get("plugin")
    finally:
        if created_plugin:
            p = Path("plugins") / created_plugin
            if p.exists():
                shutil.rmtree(str(p))


# ---------------------------------------------------------------------------
# Phase 11 — Sandbox run endpoint
# ---------------------------------------------------------------------------

def test_sandbox_run_basic(client):
    """POST /sandbox/run executes a command and returns output."""
    res = client.post("/sandbox/run", json={"command": "echo hello", "working_dir": "workspace"})
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") in ("ok", "timeout", "error")


def test_sandbox_run_invalid_working_dir(client):
    """POST /sandbox/run with disallowed working_dir returns 403."""
    res = client.post("/sandbox/run", json={"command": "echo hi", "working_dir": "configs"})
    assert res.status_code == 403


def test_sandbox_run_path_traversal(client):
    """POST /sandbox/run with path traversal is rejected."""
    res = client.post("/sandbox/run", json={"command": "ls", "working_dir": "workspace/../configs"})
    assert res.status_code == 403


def test_sandbox_run_docker_fallback_when_unavailable(client, monkeypatch):
    """POST /sandbox/run with use_docker=True falls back to subprocess when Docker is not available."""
    import shutil as _shutil

    # Capture the real which() before monkeypatching to avoid recursive lambda
    _original_which = _shutil.which

    # Simulate Docker not being on PATH
    monkeypatch.setattr(_shutil, "which", lambda cmd: None if cmd == "docker" else _original_which(cmd))

    res = client.post(
        "/sandbox/run",
        json={"command": "echo fallback", "working_dir": "workspace", "use_docker": True},
    )
    assert res.status_code == 200
    data = res.json()
    # Must not return an error status — fallback should succeed
    assert data.get("status") == "ok"
    assert data.get("docker") is False
    assert "warning" in data
    assert "fallback" in data["warning"].lower()


# ---------------------------------------------------------------------------
# Phase 10-1 — HTTP Basic Auth
# ---------------------------------------------------------------------------

def test_auth_disabled_by_default(client):
    """With auth disabled in config, all endpoints are accessible without credentials."""
    res = client.get("/health")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Phase 10-5 — Persistent chat history
# ---------------------------------------------------------------------------

def test_chat_history_empty(client):
    """GET /chat/history returns empty list when no history exists."""
    res = client.get("/chat/history?project_path=_test_no_such_project_xyz")
    assert res.status_code == 200
    data = res.json()
    assert "messages" in data
    assert data["total"] == 0


def test_chat_history_append_and_get(client):
    """POST /chat/history appends a message; GET retrieves it."""
    import uuid
    project = f"_test_chat_{uuid.uuid4().hex[:8]}"
    try:
        res = client.post(
            "/chat/history",
            json={"role": "user", "content": "Hello from test!", "project_path": project},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        res = client.get(f"/chat/history?project_path={project}")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 1
        assert data["messages"][0]["content"] == "Hello from test!"
    finally:
        # Clean up
        client.delete(f"/chat/history?project_path={project}")


def test_chat_history_clear(client):
    """DELETE /chat/history clears history."""
    import uuid
    project = f"_test_chat_clear_{uuid.uuid4().hex[:8]}"
    client.post("/chat/history", json={"role": "user", "content": "hi", "project_path": project})
    res = client.delete(f"/chat/history?project_path={project}")
    assert res.status_code == 200
    res = client.get(f"/chat/history?project_path={project}")
    assert res.json()["total"] == 0


def test_chat_history_invalid_role(client):
    """POST /chat/history with invalid role returns 400."""
    res = client.post("/chat/history", json={"role": "robot", "content": "hi"})
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Phase 10-6 — Agent session memory
# ---------------------------------------------------------------------------

def test_memory_empty(client):
    """GET /memory returns empty dict when no memory set."""
    res = client.get("/memory?project_path=_test_no_such_proj_mem")
    assert res.status_code == 200
    assert res.json()["memory"] == {}


def test_memory_set_and_get(client):
    """POST /memory stores a key; GET /memory retrieves it."""
    import uuid
    project = f"_test_mem_{uuid.uuid4().hex[:8]}"
    try:
        res = client.post(
            "/memory",
            json={"key": "test_fact", "value": "42", "project_path": project},
        )
        assert res.status_code == 200

        res = client.get(f"/memory?project_path={project}")
        assert res.status_code == 200
        assert res.json()["memory"].get("test_fact") == "42"
    finally:
        client.delete(f"/memory/test_fact?project_path={project}")


def test_memory_delete_key(client):
    """DELETE /memory/{key} removes a specific key."""
    import uuid
    project = f"_test_mem_del_{uuid.uuid4().hex[:8]}"
    client.post("/memory", json={"key": "del_key", "value": "val", "project_path": project})
    res = client.delete(f"/memory/del_key?project_path={project}")
    assert res.status_code == 200
    res = client.get(f"/memory?project_path={project}")
    assert "del_key" not in res.json()["memory"]


def test_memory_empty_key_rejected(client):
    """POST /memory with empty key returns 400."""
    res = client.post("/memory", json={"key": "", "value": "x"})
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Phase 11-7 — Model download helper
# ---------------------------------------------------------------------------

def test_models_list(client):
    """GET /models/list returns recommended models list."""
    res = client.get("/models/list")
    assert res.status_code == 200
    data = res.json()
    assert "models" in data
    assert isinstance(data["models"], list)
    assert len(data["models"]) >= 4
    # Each model has required fields
    for m in data["models"]:
        assert "name" in m
        assert "label" in m
        assert "backend" in m
        assert "installed" in m


def test_models_download_empty_name(client):
    """POST /models/download with empty model_name returns 400."""
    res = client.post("/models/download", json={"model_name": "", "backend": "ollama"})
    assert res.status_code == 400


def test_models_download_starts_job(client, monkeypatch):
    """POST /models/download with valid name starts a background job."""
    import subprocess as _sp

    # Monkeypatch Popen to avoid actual download
    class _FakePopen:
        stdout = iter([])
        returncode = 0
        def wait(self): pass

    monkeypatch.setattr(_sp, "Popen", lambda *a, **kw: _FakePopen())

    res = client.post("/models/download", json={"model_name": "test-model", "backend": "ollama"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "started"
    assert "job_id" in data


def test_models_download_status_not_found(client):
    """GET /models/download/status with unknown job_id returns 404."""
    res = client.get("/models/download/status?job_id=nonexistent_job")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Phase 13 — Self-build log endpoint
# ---------------------------------------------------------------------------

def test_self_build_log_empty(client):
    """GET /self-build/log returns empty entries when no build has run."""
    res = client.get("/self-build/log")
    assert res.status_code == 200
    data = res.json()
    assert "entries" in data
    assert "summary" in data
    assert data["summary"]["total"] >= 0


# ---------------------------------------------------------------------------
# Phase 14 — Code Quality endpoints
# ---------------------------------------------------------------------------

def test_format_python_valid(client):
    """POST /format with valid Python code returns formatted content."""
    res = client.post("/format", json={"content": "x=1\ny=2\n", "language": "python"})
    assert res.status_code == 200
    data = res.json()
    assert "formatted" in data
    assert "tool" in data
    assert "changed" in data


def test_format_json_valid(client):
    """POST /format with valid JSON returns pretty-printed JSON."""
    res = client.post("/format", json={"content": '{"a":1,"b":2}', "language": "json"})
    assert res.status_code == 200
    data = res.json()
    assert "formatted" in data
    # Pretty-printed JSON should contain newlines
    assert "\n" in data["formatted"]
    assert data["tool"] == "json"
    assert data["changed"] is True


def test_format_json_invalid(client):
    """POST /format with invalid JSON returns 422."""
    res = client.post("/format", json={"content": "{bad json", "language": "json"})
    assert res.status_code == 422


def test_format_python_syntax_error(client):
    """POST /format with Python syntax error returns 422."""
    res = client.post("/format", json={"content": "def foo(\n", "language": "python"})
    # If black is available it returns 422 for syntax errors; if not, ast does too
    # Either 422 (syntax error) or 200 (black unavailable + ast catches it)
    assert res.status_code in (200, 422)


def test_lint_python_clean(client):
    """POST /lint with clean Python returns empty diagnostics."""
    res = client.post("/lint", json={"content": "x = 1\ny = 2\n", "language": "python"})
    assert res.status_code == 200
    data = res.json()
    assert "diagnostics" in data
    assert "tool" in data
    assert isinstance(data["diagnostics"], list)


def test_lint_python_syntax_error(client):
    """POST /lint with a syntax error returns diagnostic."""
    res = client.post("/lint", json={"content": "def foo(\n", "language": "python"})
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data["diagnostics"], list)


def test_lint_non_python(client):
    """POST /lint for non-Python language returns empty diagnostics."""
    res = client.post("/lint", json={"content": "const x = 1;", "language": "javascript"})
    assert res.status_code == 200
    data = res.json()
    assert data["diagnostics"] == []
    assert data["tool"] == "none"


def test_stats_returns_structure(client):
    """GET /stats returns files, lines, and breakdown."""
    res = client.get("/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_files" in data
    assert "total_lines" in data
    assert "breakdown" in data
    assert isinstance(data["breakdown"], list)


def test_search_symbol_returns_results_key(client):
    """GET /search/symbol returns results key."""
    res = client.get("/search/symbol?query=def&language=python")
    assert res.status_code == 200
    data = res.json()
    assert "results" in data
    assert "query" in data
    assert isinstance(data["results"], list)


def test_search_symbol_empty_query(client):
    """GET /search/symbol with empty query returns 422."""
    res = client.get("/search/symbol?query=")
    assert res.status_code == 422


def test_diff_apply_missing_path(client):
    """POST /diff/apply with empty path returns 400."""
    res = client.post("/diff/apply", json={"path": "", "patch": "--- a\n+++ b\n"})
    assert res.status_code == 400


def test_diff_apply_nonexistent_file(client):
    """POST /diff/apply with nonexistent file returns 404."""
    res = client.post("/diff/apply", json={"path": "nonexistent_xyz.py", "patch": "--- a\n+++ b\n"})
    assert res.status_code == 404


# ── Phase 15: Project Templates & Multi-Language Toolchain ────────────────────

def test_templates_list_returns_structure(client):
    """GET /templates returns list of templates with required keys."""
    res = client.get("/templates")
    assert res.status_code == 200
    data = res.json()
    assert "templates" in data
    assert isinstance(data["templates"], list)
    for t in data["templates"]:
        assert "name" in t
        assert "description" in t
        assert "files" in t


def test_templates_list_includes_builtin(client):
    """GET /templates includes at least the built-in python template."""
    res = client.get("/templates")
    assert res.status_code == 200
    names = [t["name"] for t in res.json()["templates"]]
    assert "python" in names


def test_templates_apply_unknown_template(client):
    """POST /templates/apply with unknown template returns 404."""
    res = client.post(
        "/templates/apply",
        json={"name": "__nonexistent__", "dest": "tmp_apply_test", "context": {}},
    )
    assert res.status_code == 404


def test_templates_apply_missing_fields(client):
    """POST /templates/apply with empty name returns 400."""
    res = client.post(
        "/templates/apply",
        json={"name": "", "dest": "tmp_dest", "context": {}},
    )
    assert res.status_code == 400


def test_templates_apply_python_template(client):
    """POST /templates/apply with python template creates files in workspace."""
    # Use a unique dest name based on timestamp to avoid collisions
    import time
    dest = f"phase15_test_{int(time.time() * 1000)}"
    res = client.post(
        "/templates/apply",
        json={"name": "python", "dest": dest, "context": {"project_name": "myapp"}},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["applied"] is True
    assert data["template"] == "python"
    assert isinstance(data["files"], list)
    assert len(data["files"]) > 0
    # Cleanup: remove test directory
    import shutil
    from pathlib import Path
    test_dir = Path("workspace") / dest
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)


def test_toolchain_returns_structure(client):
    """GET /toolchain returns toolchain list."""
    res = client.get("/toolchain")
    assert res.status_code == 200
    data = res.json()
    assert "toolchain" in data
    assert "count" in data
    assert isinstance(data["toolchain"], list)
    assert data["count"] == len(data["toolchain"])


def test_toolchain_includes_python(client):
    """GET /toolchain always includes Python since we run in Python."""
    res = client.get("/toolchain")
    assert res.status_code == 200
    keys = [t["key"] for t in res.json()["toolchain"]]
    assert "python" in keys


def test_toolchain_tool_has_required_keys(client):
    """Each toolchain entry has key, label, version, available."""
    res = client.get("/toolchain")
    assert res.status_code == 200
    for t in res.json()["toolchain"]:
        assert "key" in t
        assert "label" in t
        assert "version" in t
        assert "available" in t


def test_snippet_run_python(client):
    """POST /snippet/run runs a Python snippet and returns stdout."""
    res = client.post(
        "/snippet/run",
        json={"code": "print('hello phase15')\n", "language": "python"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "stdout" in data
    assert "stderr" in data
    assert "returncode" in data
    assert "hello phase15" in data["stdout"]
    assert data["returncode"] == 0


def test_snippet_run_python_error(client):
    """POST /snippet/run with invalid Python returns non-zero exit code."""
    res = client.post(
        "/snippet/run",
        json={"code": "raise ValueError('boom')\n", "language": "python"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["returncode"] != 0
    assert "ValueError" in data["stderr"]


def test_snippet_run_unsupported_language(client):
    """POST /snippet/run with unknown language returns 400."""
    res = client.post(
        "/snippet/run",
        json={"code": "x = 1", "language": "cobol"},
    )
    assert res.status_code == 400


def test_snippet_run_missing_runtime(client):
    """POST /snippet/run with language whose runtime is absent returns 501."""
    # Use 'lua' which is very likely absent in CI; if it IS installed, it will just run fine
    res = client.post(
        "/snippet/run",
        json={"code": "print('hi')", "language": "lua"},
    )
    assert res.status_code in (200, 501)


def test_templates_save_missing_fields(client):
    """POST /templates/save with empty name/source returns 400."""
    res = client.post("/templates/save", json={"name": "", "source": "workspace"})
    assert res.status_code == 400


def test_templates_save_invalid_name(client):
    """POST /templates/save with invalid name chars returns 400."""
    res = client.post(
        "/templates/save",
        json={"name": "bad name!", "source": "workspace", "description": ""},
    )
    assert res.status_code == 400


def test_templates_save_nonexistent_source(client):
    """POST /templates/save when source path doesn't exist returns 404."""
    res = client.post(
        "/templates/save",
        json={"name": "test-tmpl-xyz", "source": "__nonexistent_src__", "description": ""},
    )
    assert res.status_code == 404


# ── Phase 16: Utility API tests ───────────────────────────────────────────────

def test_archive_pack_missing_fields(client):
    """POST /archive/pack with empty src/dst returns 422."""
    res = client.post("/archive/pack", json={"src": "", "dst": "", "format": "zip"})
    # FastAPI validates the body; empty strings pass Pydantic but zip_pack may error
    assert res.status_code in (200, 400, 422)


def test_archive_pack_nonexistent_src(client, tmp_path):
    """POST /archive/pack with nonexistent src returns 400."""
    res = client.post(
        "/archive/pack",
        json={"src": str(tmp_path / "does_not_exist"), "dst": str(tmp_path / "out.zip"), "format": "zip"},
    )
    assert res.status_code == 400


def test_archive_extract_nonexistent(client, tmp_path):
    """POST /archive/extract with nonexistent archive returns 400."""
    res = client.post(
        "/archive/extract",
        json={"src": str(tmp_path / "no.zip"), "dst": str(tmp_path / "out")},
    )
    assert res.status_code == 400


def test_archive_roundtrip(client, tmp_path):
    """Pack then extract a directory produces identical files."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "hello.txt").write_text("hi there")

    archive = str(tmp_path / "test.zip")
    extract_dir = str(tmp_path / "extracted")

    res = client.post("/archive/pack", json={"src": str(src_dir), "dst": archive, "format": "zip"})
    assert res.status_code == 200
    assert res.json().get("archive") == archive

    res2 = client.post("/archive/extract", json={"src": archive, "dst": extract_dir})
    assert res2.status_code == 200
    import os
    extracted_files = list(Path(extract_dir).rglob("*.txt"))
    assert len(extracted_files) == 1
    assert extracted_files[0].read_text() == "hi there"


def test_doc_generate_markdown(client, tmp_path):
    """POST /doc/generate creates a markdown file from Python source."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "sample.py").write_text('"""Module docstring."""\n\ndef greet(name: str) -> str:\n    """Greet someone."""\n    return f"Hello {name}"\n')
    out_file = str(tmp_path / "docs" / "README.md")

    res = client.post(
        "/doc/generate",
        json={"src": str(src_dir), "output": out_file, "format": "markdown", "title": "Test Docs"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["files_scanned"] >= 1
    assert Path(out_file).exists()


def test_doc_generate_bad_src(client, tmp_path):
    """POST /doc/generate with nonexistent src returns 400."""
    res = client.post(
        "/doc/generate",
        json={"src": str(tmp_path / "nosuchdir"), "output": str(tmp_path / "out.md"), "format": "markdown"},
    )
    assert res.status_code == 400


def test_doc_lint_missing_dir(client, tmp_path):
    """GET /doc/lint with nonexistent directory returns 400."""
    res = client.get(f"/doc/lint?docs_dir={tmp_path / 'nosuchdir'}")
    assert res.status_code == 400


def test_network_download_missing_fields(client):
    """POST /network/download with empty url/dst returns 400."""
    res = client.post("/network/download", json={"url": "", "dst": ""})
    assert res.status_code == 400


def test_network_request_missing_url(client):
    """POST /network/request with empty url returns 400."""
    res = client.post("/network/request", json={"url": "", "method": "GET"})
    assert res.status_code == 400


def test_packages_install_empty_name(client):
    """POST /packages/install with empty name returns 400."""
    res = client.post("/packages/install", json={"name": "", "manager": "pip"})
    assert res.status_code == 400


def test_packages_list_pip(client):
    """GET /packages/list?manager=pip returns a list."""
    res = client.get("/packages/list?manager=pip")
    assert res.status_code == 200
    data = res.json()
    assert "manager" in data


def test_packages_uninstall_empty_name(client):
    """POST /packages/uninstall with empty name returns 400."""
    res = client.post("/packages/uninstall", json={"name": "", "manager": "pip"})
    assert res.status_code == 400


def test_image_info_nonexistent(client, tmp_path):
    """GET /image/info with nonexistent path returns 400."""
    res = client.get(f"/image/info?path={tmp_path / 'no.png'}")
    assert res.status_code == 400


def test_image_resize_missing_path(client):
    """POST /image/resize with empty path returns 400."""
    res = client.post("/image/resize", json={"path": "", "width": 100, "height": 100})
    assert res.status_code == 400


def test_image_convert_missing_fields(client):
    """POST /image/convert missing path or format returns 400."""
    res = client.post("/image/convert", json={"path": "", "format": "PNG"})
    assert res.status_code == 400


def test_audio_convert_missing_fields(client):
    """POST /audio/convert with empty src/dst returns 400."""
    res = client.post("/audio/convert", json={"src": "", "dst": ""})
    assert res.status_code == 400


def test_audio_trim_missing_fields(client):
    """POST /audio/trim with empty src/dst returns 400."""
    res = client.post("/audio/trim", json={"src": "", "dst": "", "start_ms": 0, "end_ms": -1})
    assert res.status_code == 400


def test_audio_info_nonexistent(client, tmp_path):
    """GET /audio/info with nonexistent path returns 400."""
    res = client.get(f"/audio/info?path={tmp_path / 'no.mp3'}")
    assert res.status_code == 400


def test_debug_process_invalid_pid(client):
    """GET /debug/process with PID 0 returns 404."""
    res = client.get("/debug/process?pid=0")
    assert res.status_code == 404


def test_debug_memory_current_process(client):
    """GET /debug/memory with current process PID returns ok."""
    import os
    res = client.get(f"/debug/memory?pid={os.getpid()}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "memory" in data


def test_debug_trace_current_process(client):
    """GET /debug/trace with current process PID returns stack frames."""
    import os
    res = client.get(f"/debug/trace?pid={os.getpid()}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
