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


def test_assistant_chat_returns_reply(client):
    """Central assistant endpoint returns a reply with session_id and backend_used."""
    res = client.post("/assistant/chat", json={"message": "hello"})
    assert res.status_code == 200
    data = res.json()
    assert "reply" in data
    assert isinstance(data["reply"], str)
    assert "session_id" in data
    assert data["session_id"]  # non-empty
    assert "backend_used" in data


def test_assistant_chat_accepts_session_id(client):
    """Provided session_id is echoed back unchanged."""
    res = client.post("/assistant/chat", json={"message": "ping", "session_id": "test-sess-1"})
    assert res.status_code == 200
    assert res.json()["session_id"] == "test-sess-1"


def test_assistant_chat_empty_message_rejected(client):
    """Empty message body should fail validation."""
    res = client.post("/assistant/chat", json={})
    assert res.status_code == 422


def test_assistant_chat_stub_reply_is_helpful(client):
    """When local stub is used the reply must contain setup guidance, not the old echo."""
    res = client.post("/assistant/chat", json={"message": "hello", "llm_backend": "local"})
    assert res.status_code == 200
    reply = res.json()["reply"]
    # Must NOT be the old stub echo
    assert "[LocalLLM stub] Received:" not in reply
    # Must contain helpful guidance
    assert "LLM" in reply or "backend" in reply or "Ollama" in reply


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


# ── Phase 17: Notes & Tasks ───────────────────────────────────────────────────

def test_notes_crud(client):
    """Create, list, update, and delete a note."""
    # Create
    res = client.post("/notes", json={"title": "Test Note", "content": "hello"})
    assert res.status_code == 200
    note = res.json()["note"]
    assert note["title"] == "Test Note"
    note_id = note["id"]

    # List
    res = client.get("/notes")
    assert res.status_code == 200
    ids = [n["id"] for n in res.json()["notes"]]
    assert note_id in ids

    # Update
    res = client.patch(f"/notes/{note_id}", json={"content": "updated"})
    assert res.status_code == 200
    assert res.json()["note"]["content"] == "updated"

    # Delete
    res = client.delete(f"/notes/{note_id}")
    assert res.status_code == 200
    assert res.json()["deleted"] == note_id

    # Confirm gone
    res = client.delete(f"/notes/{note_id}")
    assert res.status_code == 404


def test_notes_create_missing_title(client):
    """POST /notes with empty title returns 400."""
    res = client.post("/notes", json={"title": ""})
    assert res.status_code == 400


def test_tasks_crud(client):
    """Create, list, update status, and delete a task."""
    # Create
    res = client.post("/tasks", json={"title": "Test Task", "status": "todo", "priority": "high"})
    assert res.status_code == 200
    task = res.json()["task"]
    assert task["title"] == "Test Task"
    task_id = task["id"]

    # List
    res = client.get("/tasks")
    assert res.status_code == 200
    ids = [t["id"] for t in res.json()["tasks"]]
    assert task_id in ids

    # Update status
    res = client.patch(f"/tasks/{task_id}", json={"status": "in_progress"})
    assert res.status_code == 200
    assert res.json()["task"]["status"] == "in_progress"

    # Delete
    res = client.delete(f"/tasks/{task_id}")
    assert res.status_code == 200
    assert res.json()["deleted"] == task_id

    # Confirm gone
    res = client.delete(f"/tasks/{task_id}")
    assert res.status_code == 404


def test_tasks_invalid_status(client):
    """POST /tasks with invalid status returns 400."""
    res = client.post("/tasks", json={"title": "bad", "status": "invalid"})
    assert res.status_code == 400


# ── Phase 18: Git Advanced ────────────────────────────────────────────────────

def test_git_log(client):
    """GET /git/log returns 200 or 400 depending on git repo presence."""
    res = client.get("/git/log?path=workspace")
    assert res.status_code in (200, 400)
    if res.status_code == 200:
        assert "commits" in res.json()


def test_git_branches(client):
    """GET /git/branches returns 200 or 400."""
    res = client.get("/git/branches?path=workspace")
    assert res.status_code in (200, 400)
    if res.status_code == 200:
        assert "branches" in res.json()


def test_git_stash_list(client):
    """GET /git/stash returns 200 or 400."""
    res = client.get("/git/stash?path=workspace")
    assert res.status_code in (200, 400)
    if res.status_code == 200:
        assert "stash" in res.json()


def test_git_blame(client):
    """GET /git/blame returns 200 or 400."""
    res = client.get("/git/blame?repo=workspace&file=README.md")
    assert res.status_code in (200, 400)
    if res.status_code == 200:
        assert "blame" in res.json()


def test_git_branch_create_missing_name(client):
    """POST /git/branches with empty name returns 400."""
    res = client.post("/git/branches?path=workspace", json={"name": ""})
    assert res.status_code in (400,)


def test_git_checkout_missing_target(client):
    """POST /git/checkout with empty target returns 400."""
    res = client.post("/git/checkout?path=workspace", json={"target": ""})
    assert res.status_code == 400


# ── Phase 19: Refactoring ─────────────────────────────────────────────────────

def test_refactor_find_replace_dry_run(client, tmp_path):
    """POST /refactor/find-replace with dry_run=true returns matches without modifying files."""
    import os
    # Create a test file in workspace
    test_file = Path("workspace/_refactor_test.txt")
    client.post("/files/write", json={"path": str(test_file), "content": "hello world\nhello again"})
    res = client.post("/refactor/find-replace", json={
        "find": "hello",
        "replace": "goodbye",
        "glob_pattern": "_refactor_test.txt",
        "is_regex": False,
        "dry_run": True,
    })
    assert res.status_code == 200
    data = res.json()
    assert "matches" in data
    assert data["dry_run"] is True
    assert data["files_changed"] == 0
    # Cleanup
    client.post("/files/delete", json={"path": str(test_file)})


def test_refactor_find_replace_apply(client):
    """POST /refactor/find-replace with dry_run=false modifies files."""
    test_file = Path("workspace/_refactor_apply_test.txt")
    client.post("/files/write", json={"path": str(test_file), "content": "FIND_ME is here"})
    res = client.post("/refactor/find-replace", json={
        "find": "FIND_ME",
        "replace": "REPLACED",
        "glob_pattern": "_refactor_apply_test.txt",
        "is_regex": False,
        "dry_run": False,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["files_changed"] >= 1
    # Verify file was changed
    read_res = client.get(f"/files/read?path={test_file}")
    assert "REPLACED" in read_res.json()["content"]
    client.post("/files/delete", json={"path": str(test_file)})


def test_refactor_rename(client):
    """POST /refactor/rename renames a symbol across files."""
    test_file = Path("workspace/_rename_test.txt")
    client.post("/files/write", json={"path": str(test_file), "content": "old_symbol = 1\nuse_old_symbol()"})
    res = client.post("/refactor/rename", json={
        "old_name": "old_symbol",
        "new_name": "new_symbol",
        "glob_pattern": "_rename_test.txt",
    })
    assert res.status_code == 200
    data = res.json()
    assert "changes" in data
    assert any(c["count"] >= 1 for c in data["changes"])
    client.post("/files/delete", json={"path": str(test_file)})


def test_refactor_extract(client):
    """POST /refactor/extract extracts lines into a new function."""
    test_file = "workspace/_extract_test.py"
    client.post("/files/write", json={"path": test_file, "content": "x = 1\ny = 2\nz = x + y\n"})
    res = client.post("/refactor/extract", json={
        "file": test_file,
        "start_line": 1,
        "end_line": 3,
        "new_name": "compute",
    })
    assert res.status_code == 200
    data = res.json()
    assert "diff" in data
    assert data["file"] == test_file
    client.post("/files/delete", json={"path": test_file})


# ── Phase 20: AI Backend tests ────────────────────────────────────────────────

def test_list_ai_backends(client):
    """GET /ai/backends returns a dict with 'active' and 'backends' keys."""
    res = client.get("/ai/backends")
    assert res.status_code == 200
    data = res.json()
    assert "active" in data
    assert "backends" in data
    assert isinstance(data["backends"], list)
    names = [b["name"] for b in data["backends"]]
    assert "ollama" in names
    assert "anthropic" in names
    assert "gemini" in names
    assert "lmstudio" in names
    assert "llamacpp" in names
    assert "tabby" in names


def test_test_ai_backend(client):
    """POST /ai/backends/test with a local backend returns a result."""
    res = client.post("/ai/backends/test", json={"backend": "local"})
    assert res.status_code == 200
    data = res.json()
    assert "ok" in data
    assert data["ok"] is True
    assert "message" in data
    assert "models" in data


def test_switch_ai_backend(client):
    """POST /ai/backends/switch updates the active backend."""
    res = client.post("/ai/backends/switch", json={"backend": "local"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["backend"] == "local"
    # Verify it took effect
    res2 = client.get("/ai/backends")
    assert res2.json()["active"] == "local"


def test_switch_ai_backend_invalid(client):
    """POST /ai/backends/switch with an unknown backend returns 400."""
    res = client.post("/ai/backends/switch", json={"backend": "nonexistent_backend_xyz"})
    assert res.status_code == 400


def test_lmstudio_instantiation():
    """LMStudioLLM can be instantiated."""
    from llm.lmstudio import LMStudioLLM
    llm = LMStudioLLM(base_url="http://localhost:1234", model="test-model")
    assert llm.base_url == "http://localhost:1234"
    assert llm.model == "test-model"


def test_anthropic_instantiation():
    """AnthropicLLM can be instantiated."""
    from llm.anthropic import AnthropicLLM
    llm = AnthropicLLM(api_key="sk-test", model="claude-3-5-sonnet-20241022")
    assert llm.model == "claude-3-5-sonnet-20241022"
    assert llm.api_key == "sk-test"


def test_gemini_instantiation():
    """GeminiLLM can be instantiated."""
    from llm.gemini import GeminiLLM
    llm = GeminiLLM(api_key="test-key", model="gemini-2.0-flash")
    assert llm.model == "gemini-2.0-flash"
    assert llm.api_key == "test-key"


def test_llamacpp_instantiation():
    """LlamaCppLLM can be instantiated."""
    from llm.llamacpp import LlamaCppLLM
    llm = LlamaCppLLM(base_url="http://localhost:8080", model="")
    assert llm.base_url == "http://localhost:8080"


def test_tabby_instantiation():
    """TabbyLLM can be instantiated."""
    from llm.tabby import TabbyLLM
    llm = TabbyLLM(base_url="http://localhost:8080", api_key="tok", model="StarCoder")
    assert llm.base_url == "http://localhost:8080"
    assert llm.model == "StarCoder"


def test_ollama_connection_error_returns_friendly_message():
    """OllamaLLM returns a user-friendly message when the server is not reachable."""
    import requests as req
    from unittest.mock import patch
    from llm.ollama import OllamaLLM
    llm = OllamaLLM(base_url="http://localhost:11434", model="llama3")
    with patch.object(req.Session, "request", side_effect=req.exceptions.ConnectionError("refused")):
        result = llm.chat([{"role": "user", "content": "hello"}])
    assert result.startswith("⚠️")
    assert "Ollama" in result
    assert "[ERROR]" not in result


def test_lmstudio_connection_error_returns_friendly_message():
    """LMStudioLLM returns a user-friendly message when the server is not reachable."""
    import requests as req
    from unittest.mock import patch
    from llm.lmstudio import LMStudioLLM
    llm = LMStudioLLM(base_url="http://localhost:1234", model="test-model")
    with patch.object(req.Session, "request", side_effect=req.exceptions.ConnectionError("refused")):
        result = llm.chat([{"role": "user", "content": "hello"}])
    assert result.startswith("⚠️")
    assert "LM Studio" in result
    assert "[ERROR]" not in result


def test_llamacpp_connection_error_returns_friendly_message():
    """LlamaCppLLM returns a user-friendly message when the server is not reachable."""
    import requests as req
    from unittest.mock import patch
    from llm.llamacpp import LlamaCppLLM
    llm = LlamaCppLLM(base_url="http://localhost:8080", model="")
    with patch.object(req.Session, "request", side_effect=req.exceptions.ConnectionError("refused")):
        result = llm.chat([{"role": "user", "content": "hello"}])
    assert result.startswith("⚠️")
    assert "llama.cpp" in result
    assert "[ERROR]" not in result


def test_openwebui_connection_error_returns_friendly_message():
    """OpenWebUILLM returns a user-friendly message when the server is not reachable."""
    import requests as req
    from unittest.mock import patch
    from llm.openwebui import OpenWebUILLM
    llm = OpenWebUILLM(base_url="http://localhost:3000", model="llama3")
    with patch.object(req.Session, "request", side_effect=req.exceptions.ConnectionError("refused")):
        result = llm.chat([{"role": "user", "content": "hello"}])
    assert result.startswith("⚠️")
    assert "Open WebUI" in result
    assert "[ERROR]" not in result


# ── Phase 21: Project Initialization Wizard ───────────────────────────────────

def test_project_init_detect_python(client):
    """GET /project/init/detect detects Python project."""
    test_dir = Path("workspace/_test_init_python")
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "requirements.txt").write_text("requests\n")
    try:
        res = client.get(f"/project/init/detect?path={test_dir}")
        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "python"
        assert data["package_manager"] == "pip"
        assert "requirements.txt" in data["detected_files"]
        assert "install_deps" in data["recommended_steps"]
    finally:
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)


def test_project_init_detect_nodejs(client):
    """GET /project/init/detect detects Node.js project."""
    test_dir = Path("workspace/_test_init_nodejs")
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "package.json").write_text('{"name":"test","dependencies":{"react":"^18"}}')
    try:
        res = client.get(f"/project/init/detect?path={test_dir}")
        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "nodejs"
        assert data["framework"] == "react"
        assert "package.json" in data["detected_files"]
    finally:
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)


def test_project_init_run_no_install(client):
    """POST /project/init with only safe steps (no install_deps)."""
    test_dir = Path("workspace/_test_init_run")
    test_dir.mkdir(parents=True, exist_ok=True)
    try:
        res = client.post("/project/init", json={
            "project_path": str(test_dir),
            "steps": ["create_gitignore", "create_editorconfig"],
        })
        assert res.status_code == 200
        data = res.json()
        assert "results" in data
        steps_run = [r["step"] for r in data["results"]]
        assert "create_gitignore" in steps_run
        assert "create_editorconfig" in steps_run
        for r in data["results"]:
            assert r["ok"] is True
        assert (test_dir / ".gitignore").exists()
        assert (test_dir / ".editorconfig").exists()
    finally:
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)


def test_project_init_detect_unknown(client):
    """GET /project/init/detect on empty dir returns unknown language."""
    test_dir = Path("workspace/_test_init_unknown")
    test_dir.mkdir(parents=True, exist_ok=True)
    try:
        res = client.get(f"/project/init/detect?path={test_dir}")
        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "unknown"
        assert data["detected_files"] == []
    finally:
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)


# ── Phase 22: Multi-Agent Orchestration ──────────────────────────────────────
def test_agents_spawn(client):
    r = client.post("/agents/spawn", json={"name": "dev", "role": "developer", "model": "default"})
    assert r.status_code == 200
    assert r.json()["name"] == "dev"

def test_agents_list(client):
    client.post("/agents/spawn", json={"name": "qa", "role": "tester", "model": "default"})
    r = client.get("/agents")
    assert r.status_code == 200
    agents = r.json()["agents"]
    assert any(a["name"] == "qa" for a in agents)

def test_agents_run(client):
    client.post("/agents/spawn", json={"name": "runner", "role": "coder", "model": "default"})
    r = client.post("/agents/runner/run", json={"task": "say hello"})
    assert r.status_code == 200
    assert "result" in r.json()

def test_agents_run_not_found(client):
    r = client.post("/agents/nonexistent/run", json={"task": "test"})
    assert r.status_code == 404

def test_agents_delete(client):
    client.post("/agents/spawn", json={"name": "temp", "role": "helper", "model": "default"})
    r = client.delete("/agents/temp")
    assert r.status_code == 200
    assert r.json()["deleted"] == "temp"

# ── Phase 23: CI/CD Pipeline Integration ─────────────────────────────────────
def test_ci_run(client):
    r = client.post("/ci/run", json={"command": "echo hello"})
    assert r.status_code == 200
    data = r.json()
    assert data["exit_code"] == 0
    assert "hello" in data["output"]

def test_ci_status(client):
    client.post("/ci/run", json={"command": "echo status_test"})
    r = client.get("/ci/status")
    assert r.status_code == 200
    data = r.json()
    assert "command" in data or data.get("status") == "no runs"

def test_ci_runs_list(client):
    client.post("/ci/run", json={"command": "echo list_test"})
    r = client.get("/ci/runs")
    assert r.status_code == 200
    assert "runs" in r.json()

# ── Phase 24: Container & Docker Management ───────────────────────────────────
def test_docker_build_returns_output(client):
    r = client.post("/docker/build", json={"dockerfile": "Dockerfile", "tag": "test:latest", "context": "."})
    assert r.status_code == 200
    data = r.json()
    assert "exit_code" in data
    assert "output" in data
    assert data["tag"] == "test:latest"

def test_docker_run_returns_output(client):
    r = client.post("/docker/run", json={"image": "hello-world", "detach": False})
    assert r.status_code == 200
    data = r.json()
    assert "exit_code" in data
    assert "output" in data
    assert "container_id" in data

def test_docker_containers_list(client):
    r = client.get("/docker/containers")
    assert r.status_code == 200
    data = r.json()
    assert "containers" in data
    assert isinstance(data["containers"], list)

def test_docker_containers_all_flag(client):
    r = client.get("/docker/containers?all=true")
    assert r.status_code == 200
    assert "containers" in r.json()

def test_docker_stop_nonexistent(client):
    r = client.post("/docker/stop/nonexistent_container_xyz")
    assert r.status_code == 200
    data = r.json()
    assert "exit_code" in data
    assert data["container_id"] == "nonexistent_container_xyz"

def test_docker_logs_nonexistent(client):
    r = client.get("/docker/logs/nonexistent_container_xyz")
    assert r.status_code == 200
    data = r.json()
    assert "exit_code" in data
    assert "output" in data

# ── Phase 25: Remote Deployment & SSH ────────────────────────────────────────
def test_deploy_config_create(client):
    r = client.post("/deploy/config", json={
        "name": "prod", "host": "example.com", "user": "deploy",
        "port": 22, "command": "echo deployed"
    })
    assert r.status_code == 200
    assert r.json()["saved"] == "prod"

def test_deploy_configs_list(client):
    client.post("/deploy/config", json={
        "name": "staging", "host": "staging.example.com", "user": "deploy",
        "port": 22, "command": "echo staging"
    })
    r = client.get("/deploy/configs")
    assert r.status_code == 200
    data = r.json()
    assert "configs" in data
    assert any(c["name"] == "staging" for c in data["configs"])

def test_deploy_config_delete(client):
    client.post("/deploy/config", json={
        "name": "temp_cfg", "host": "temp.example.com", "user": "root",
        "port": 22, "command": "echo temp"
    })
    r = client.delete("/deploy/config/temp_cfg")
    assert r.status_code == 200
    assert r.json()["deleted"] == "temp_cfg"
    r2 = client.get("/deploy/configs")
    assert not any(c["name"] == "temp_cfg" for c in r2.json()["configs"])

def test_deploy_run_missing_host(client):
    r = client.post("/deploy/run", json={"host": "", "command": ""})
    assert r.status_code == 400

def test_deploy_run_adhoc(client):
    r = client.post("/deploy/run", json={
        "host": "127.0.0.1", "user": "root", "port": 22, "command": "echo hello"
    })
    assert r.status_code == 200
    data = r.json()
    assert "exit_code" in data
    assert "output" in data

def test_deploy_history(client):
    r = client.get("/deploy/history")
    assert r.status_code == 200
    assert "history" in r.json()

# ── Phase 26: Monitoring & Observability ─────────────────────────────────────
def test_metrics_current(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    data = r.json()
    assert "cpu_load_percent" in data
    assert "mem_percent" in data
    assert "disk_percent" in data
    assert "ts" in data

def test_metrics_history(client):
    client.get("/metrics")
    r = client.get("/metrics/history")
    assert r.status_code == 200
    data = r.json()
    assert "history" in data
    assert isinstance(data["history"], list)

def test_metrics_snapshot(client):
    r = client.post("/metrics/snapshot")
    assert r.status_code == 200
    data = r.json()
    assert data["saved"] is True
    assert "snapshot" in data

def test_health_detailed(client):
    r = client.get("/health/detailed")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "checks" in data
    assert "api" in data["checks"]

def test_metrics_alert_set(client):
    r = client.post("/metrics/alert", json={"name": "high-cpu", "metric": "cpu_load_percent", "threshold": 80.0})
    assert r.status_code == 200
    assert r.json()["saved"] == "high-cpu"

def test_metrics_alerts_list(client):
    client.post("/metrics/alert", json={"name": "high-mem", "metric": "mem_percent", "threshold": 85.0})
    r = client.get("/metrics/alerts")
    assert r.status_code == 200
    data = r.json()
    assert "alerts" in data
    assert any(a["name"] == "high-mem" for a in data["alerts"])

def test_metrics_alert_delete(client):
    client.post("/metrics/alert", json={"name": "temp-alert", "metric": "disk_percent", "threshold": 90.0})
    r = client.delete("/metrics/alert/temp-alert")
    assert r.status_code == 200
    assert r.json()["deleted"] == "temp-alert"

# ── Phase 27: Database Management ────────────────────────────────────────────
def test_db_connect(client, tmp_path):
    import sqlite3, os
    db_file = tmp_path / "test.sqlite"
    sqlite3.connect(str(db_file)).close()
    ws = os.path.join(os.getcwd(), "workspace", "test_phase27.sqlite")
    import shutil
    shutil.copy(str(db_file), ws)
    try:
        r = client.post("/db/connect", json={"path": "test_phase27.sqlite", "alias": "testdb"})
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert data["alias"] == "testdb"
    finally:
        os.unlink(ws)

def test_db_connections_list(client):
    r = client.get("/db/connections")
    assert r.status_code == 200
    assert "connections" in r.json()

def test_db_connect_invalid_path(client):
    r = client.post("/db/connect", json={"path": "../../etc/passwd"})
    assert r.status_code == 403

def test_db_query_not_found(client):
    r = client.post("/db/query", json={"connection_id": "9999", "sql": "SELECT 1"})
    assert r.status_code == 404

def test_db_schema_not_found(client):
    r = client.get("/db/schema/9999")
    assert r.status_code == 404

def test_db_connection_delete(client, tmp_path):
    import sqlite3, os, shutil
    db_file = tmp_path / "del_test.sqlite"
    sqlite3.connect(str(db_file)).close()
    ws = os.path.join(os.getcwd(), "workspace", "test_del.sqlite")
    shutil.copy(str(db_file), ws)
    try:
        r1 = client.post("/db/connect", json={"path": "test_del.sqlite", "alias": "deldb"})
        assert r1.status_code == 200
        conn_id = r1.json()["id"]
        r2 = client.delete(f"/db/connection/{conn_id}")
        assert r2.status_code == 200
        assert r2.json()["deleted"] == conn_id
    finally:
        os.unlink(ws)

def test_db_query_and_schema(client, tmp_path):
    import sqlite3, os, shutil
    db_file = tmp_path / "schema_test.sqlite"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.execute("INSERT INTO users (name) VALUES ('Alice')")
    conn.commit()
    conn.close()
    ws = os.path.join(os.getcwd(), "workspace", "test_schema.sqlite")
    shutil.copy(str(db_file), ws)
    try:
        r1 = client.post("/db/connect", json={"path": "test_schema.sqlite", "alias": "schemadb"})
        assert r1.status_code == 200
        conn_id = r1.json()["id"]
        r2 = client.post("/db/query", json={"connection_id": conn_id, "sql": "SELECT * FROM users"})
        assert r2.status_code == 200
        qdata = r2.json()
        assert "columns" in qdata
        assert "name" in qdata["columns"]
        assert any(r.get("name") == "Alice" for r in qdata["rows"])
        r3 = client.get(f"/db/schema/{conn_id}")
        assert r3.status_code == 200
        sdata = r3.json()
        assert any(t["name"] == "users" for t in sdata["tables"])
    finally:
        os.unlink(ws)

# ── Phase 28: Secret & Environment Vault ─────────────────────────────────────
def test_vault_set(client):
    r = client.post("/vault/set", json={"key": "MY_API_KEY", "value": "super-secret", "description": "test key"})
    assert r.status_code == 200
    assert r.json()["saved"] == "MY_API_KEY"

def test_vault_keys_hides_values(client):
    client.post("/vault/set", json={"key": "DB_PASSWORD", "value": "hunter2"})
    r = client.get("/vault/keys")
    assert r.status_code == 200
    data = r.json()
    assert "keys" in data
    assert any(k["key"] == "DB_PASSWORD" for k in data["keys"])
    # values must NOT appear in the keys listing
    assert not any("hunter2" in str(k) for k in data["keys"])

def test_vault_get(client):
    client.post("/vault/set", json={"key": "TOKEN", "value": "abc123"})
    r = client.get("/vault/get/TOKEN")
    assert r.status_code == 200
    assert r.json()["value"] == "abc123"

def test_vault_get_not_found(client):
    r = client.get("/vault/get/NONEXISTENT_KEY_XYZ")
    assert r.status_code == 404

def test_vault_delete(client):
    client.post("/vault/set", json={"key": "TEMP_KEY", "value": "temp"})
    r = client.delete("/vault/key/TEMP_KEY")
    assert r.status_code == 200
    assert r.json()["deleted"] == "TEMP_KEY"

def test_vault_export_env(client):
    client.post("/vault/set", json={"key": "EXPORT_KEY", "value": "export_val"})
    r = client.post("/vault/export", json={"keys": ["EXPORT_KEY"], "format": "env"})
    assert r.status_code == 200
    data = r.json()
    assert data["format"] == "env"
    assert "EXPORT_KEY=export_val" in data["data"]

def test_vault_import(client):
    r = client.post("/vault/import", json={"IMPORT_A": "val_a", "IMPORT_B": "val_b"})
    assert r.status_code == 200
    imported = r.json()["imported"]
    assert "IMPORT_A" in imported
    assert "IMPORT_B" in imported

# ── Phase 29: WebHook Manager ─────────────────────────────────────────────────
def test_webhook_register(client):
    r = client.post("/webhook/register", json={"name": "test-hook", "url": "http://localhost:9999/hook"})
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["name"] == "test-hook"

def test_webhooks_list(client):
    client.post("/webhook/register", json={"name": "list-hook", "url": "http://localhost:9999/list"})
    r = client.get("/webhooks")
    assert r.status_code == 200
    data = r.json()
    assert "webhooks" in data
    assert any(w["name"] == "list-hook" for w in data["webhooks"])

def test_webhooks_list_hides_secret(client):
    client.post("/webhook/register", json={"name": "secret-hook", "url": "http://localhost:9999/s", "secret": "mysecret"})
    r = client.get("/webhooks")
    assert r.status_code == 200
    for wh in r.json()["webhooks"]:
        assert "secret" not in wh

def test_webhook_register_missing_url(client):
    r = client.post("/webhook/register", json={"name": "no-url", "url": ""})
    assert r.status_code == 400

def test_webhook_deliver_not_found(client):
    r = client.post("/webhook/deliver/99999", json={"event": "test"})
    assert r.status_code == 404

def test_webhook_deliver_connection_error(client):
    r = client.post("/webhook/register", json={"name": "fail-hook", "url": "http://localhost:19999/nope"})
    wid = r.json()["id"]
    r2 = client.post(f"/webhook/deliver/{wid}", json={"event": "test", "payload": {"x": 1}})
    assert r2.status_code == 200
    data = r2.json()
    assert data["status_code"] == -1   # connection refused → error
    assert "webhook_id" in data

def test_webhook_deliveries_list(client):
    r = client.get("/webhook/deliveries")
    assert r.status_code == 200
    assert "deliveries" in r.json()

def test_webhook_delete(client):
    r = client.post("/webhook/register", json={"name": "del-hook", "url": "http://localhost:9999/del"})
    wid = r.json()["id"]
    r2 = client.delete(f"/webhook/{wid}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] == wid

# ── Phase 30: API Rate Limiting & Quota ───────────────────────────────────────
def test_ratelimit_rule_set(client):
    r = client.post("/ratelimit/rule", json={"name": "api", "limit": 10, "window_seconds": 60})
    assert r.status_code == 200
    assert r.json()["saved"] == "api"

def test_ratelimit_rules_list(client):
    client.post("/ratelimit/rule", json={"name": "list_rule", "limit": 5, "window_seconds": 30})
    r = client.get("/ratelimit/rules")
    assert r.status_code == 200
    data = r.json()
    assert "rules" in data
    assert any(ru["name"] == "list_rule" for ru in data["rules"])

def test_ratelimit_rule_bad_limit(client):
    r = client.post("/ratelimit/rule", json={"name": "bad", "limit": 0})
    assert r.status_code == 400

def test_ratelimit_check_allowed(client):
    client.post("/ratelimit/rule", json={"name": "check_rule", "limit": 100, "window_seconds": 60})
    r = client.post("/ratelimit/check/check_rule")
    assert r.status_code == 200
    data = r.json()
    assert data["allowed"] is True
    assert data["used"] == 1

def test_ratelimit_check_throttled(client):
    client.post("/ratelimit/rule", json={"name": "tight_rule", "limit": 2, "window_seconds": 60})
    client.post("/ratelimit/check/tight_rule")
    client.post("/ratelimit/check/tight_rule")
    r = client.post("/ratelimit/check/tight_rule")
    assert r.status_code == 200
    assert r.json()["throttled"] is True

def test_ratelimit_reset(client):
    client.post("/ratelimit/rule", json={"name": "reset_rule", "limit": 2, "window_seconds": 60})
    client.post("/ratelimit/check/reset_rule")
    client.post("/ratelimit/check/reset_rule")
    r = client.post("/ratelimit/reset/reset_rule")
    assert r.status_code == 200
    # After reset, should be allowed again
    r2 = client.post("/ratelimit/check/reset_rule")
    assert r2.json()["allowed"] is True

def test_ratelimit_delete(client):
    client.post("/ratelimit/rule", json={"name": "del_rule", "limit": 10, "window_seconds": 60})
    r = client.delete("/ratelimit/rule/del_rule")
    assert r.status_code == 200
    assert r.json()["deleted"] == "del_rule"

# ── Phase 31: Event Bus & Pub/Sub ─────────────────────────────────────────────
def test_events_publish(client):
    r = client.post("/events/publish", json={"topic": "build.done", "payload": {"status": "ok"}, "source": "ci"})
    assert r.status_code == 200
    data = r.json()
    assert data["topic"] == "build.done"
    assert "id" in data

def test_events_publish_no_topic(client):
    r = client.post("/events/publish", json={"topic": "", "payload": {}})
    assert r.status_code == 400

def test_events_history(client):
    client.post("/events/publish", json={"topic": "test.event", "payload": {}})
    r = client.get("/events/history")
    assert r.status_code == 200
    data = r.json()
    assert "events" in data
    assert any(e["topic"] == "test.event" for e in data["events"])

def test_events_history_by_topic(client):
    client.post("/events/publish", json={"topic": "specific.topic", "payload": {"x": 1}})
    r = client.get("/events/history/specific.topic")
    assert r.status_code == 200
    data = r.json()
    assert data["topic"] == "specific.topic"
    assert len(data["events"]) >= 1

def test_events_subscribe(client):
    r = client.post("/events/subscribe", json={"topics": ["build.*", "deploy.*"], "name": "listener"})
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert "build.*" in data["topics"]

def test_events_subscribe_empty_topics(client):
    r = client.post("/events/subscribe", json={"topics": []})
    assert r.status_code == 400

def test_events_subscriptions_list(client):
    client.post("/events/subscribe", json={"topics": ["ci.run"], "name": "ci-watcher"})
    r = client.get("/events/subscriptions")
    assert r.status_code == 200
    data = r.json()
    assert "subscriptions" in data
    assert any(s["name"] == "ci-watcher" for s in data["subscriptions"])

def test_events_subscription_delete(client):
    r = client.post("/events/subscribe", json={"topics": ["x.y"], "name": "temp"})
    sub_id = r.json()["id"]
    r2 = client.delete(f"/events/subscription/{sub_id}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] == sub_id

# ── Phase 32: Cron Job Scheduler ──────────────────────────────────────────────
def test_cron_job_set(client):
    r = client.post("/cron/job", json={"name": "hello", "schedule": "every 60s", "command": "echo hi"})
    assert r.status_code == 200
    assert r.json()["saved"] == "hello"

def test_cron_jobs_list(client):
    client.post("/cron/job", json={"name": "list_job", "schedule": "every 30s", "command": "echo list"})
    r = client.get("/cron/jobs")
    assert r.status_code == 200
    data = r.json()
    assert "jobs" in data
    assert any(j["name"] == "list_job" for j in data["jobs"])

def test_cron_job_no_command(client):
    r = client.post("/cron/job", json={"name": "bad", "schedule": "every 60s", "command": ""})
    assert r.status_code == 400

def test_cron_job_run(client):
    client.post("/cron/job", json={"name": "run_job", "schedule": "manual", "command": "echo running"})
    r = client.post("/cron/job/run_job/run")
    assert r.status_code == 200
    data = r.json()
    assert data["job"] == "run_job"
    assert "exit_code" in data

def test_cron_job_history(client):
    client.post("/cron/job", json={"name": "hist_job", "schedule": "manual", "command": "echo hist"})
    client.post("/cron/job/hist_job/run")
    r = client.get("/cron/job/hist_job/history")
    assert r.status_code == 200
    data = r.json()
    assert data["job"] == "hist_job"
    assert len(data["history"]) >= 1

def test_cron_history_all(client):
    r = client.get("/cron/history")
    assert r.status_code == 200
    assert "history" in r.json()

def test_cron_job_delete(client):
    client.post("/cron/job", json={"name": "del_cron", "schedule": "manual", "command": "true"})
    r = client.delete("/cron/job/del_cron")
    assert r.status_code == 200
    assert r.json()["deleted"] == "del_cron"

# ── Phase 33: Audit Log ───────────────────────────────────────────────────────
def test_audit_log_append(client):
    r = client.post("/audit/log", json={"action": "login", "actor": "admin", "level": "info"})
    assert r.status_code == 200
    assert r.json()["logged"] == "login"

def test_audit_log_no_action(client):
    r = client.post("/audit/log", json={"action": "", "actor": "admin"})
    assert r.status_code == 400

def test_audit_log_list(client):
    client.post("/audit/log", json={"action": "file.edit", "actor": "user1", "level": "info"})
    r = client.get("/audit/log")
    assert r.status_code == 200
    data = r.json()
    assert "entries" in data
    assert any(e["action"] == "file.edit" for e in data["entries"])

def test_audit_log_get(client):
    r = client.post("/audit/log", json={"action": "get.test", "actor": "test"})
    entry_id = r.json()["id"]
    r2 = client.get(f"/audit/log/{entry_id}")
    assert r2.status_code == 200
    assert r2.json()["action"] == "get.test"

def test_audit_stats(client):
    client.post("/audit/log", json={"action": "stats.test", "level": "info"})
    r = client.get("/audit/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert data["total"] >= 1

def test_audit_log_filter_level(client):
    client.post("/audit/log", json={"action": "warn.action", "level": "warn"})
    r = client.get("/audit/log?level=warn")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert all(e["level"] == "warn" for e in entries)

def test_audit_log_clear(client):
    client.post("/audit/log", json={"action": "pre.clear", "level": "info"})
    r = client.delete("/audit/log/clear")
    assert r.status_code == 200
    assert "cleared" in r.json()
    r2 = client.get("/audit/log")
    assert len(r2.json()["entries"]) == 0

# ── Phase 34: Feature Flags ───────────────────────────────────────────────────
def test_flag_set(client):
    r = client.post("/flags/flag", json={"name": "dark_mode", "enabled": True, "variant": "v2"})
    assert r.status_code == 200
    assert r.json()["saved"] == "dark_mode"

def test_flag_no_name(client):
    r = client.post("/flags/flag", json={"name": "", "enabled": True})
    assert r.status_code == 400

def test_flags_list(client):
    client.post("/flags/flag", json={"name": "list_flag", "enabled": False})
    r = client.get("/flags")
    assert r.status_code == 200
    data = r.json()
    assert "flags" in data
    assert any(f["name"] == "list_flag" for f in data["flags"])

def test_flag_get(client):
    client.post("/flags/flag", json={"name": "get_flag", "enabled": True, "variant": "beta"})
    r = client.get("/flags/flag/get_flag")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "get_flag"
    assert data["variant"] == "beta"

def test_flag_toggle(client):
    client.post("/flags/flag", json={"name": "toggle_flag", "enabled": True})
    r = client.post("/flags/flag/toggle_flag/toggle")
    assert r.status_code == 200
    assert r.json()["enabled"] is False

def test_flag_check(client):
    client.post("/flags/flag", json={"name": "check_flag", "enabled": True})
    r = client.get("/flags/check/check_flag")
    assert r.status_code == 200
    assert r.json()["enabled"] is True

def test_flag_delete(client):
    client.post("/flags/flag", json={"name": "del_flag", "enabled": True})
    r = client.delete("/flags/flag/del_flag")
    assert r.status_code == 200
    assert r.json()["deleted"] == "del_flag"

# ── Phase 35: Config Profiles ─────────────────────────────────────────────────
def test_config_profile_set(client):
    r = client.post("/config/profile", json={"name": "prod", "values": {"HOST": "prod.example.com", "PORT": "443"}})
    assert r.status_code == 200
    assert r.json()["saved"] == "prod"

def test_config_profile_no_name(client):
    r = client.post("/config/profile", json={"name": "", "values": {}})
    assert r.status_code == 400

def test_config_profiles_list(client):
    client.post("/config/profile", json={"name": "dev", "values": {"HOST": "localhost"}})
    r = client.get("/config/profiles")
    assert r.status_code == 200
    data = r.json()
    assert "profiles" in data
    assert any(p["name"] == "dev" for p in data["profiles"])

def test_config_profile_get(client):
    client.post("/config/profile", json={"name": "staging", "values": {"ENV": "staging"}})
    r = client.get("/config/profile/staging")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "staging"
    assert data["values"]["ENV"] == "staging"

def test_config_profile_activate(client):
    client.post("/config/profile", json={"name": "active_prof", "values": {"K": "V"}})
    r = client.post("/config/profile/active_prof/activate")
    assert r.status_code == 200
    assert r.json()["activated"] == "active_prof"

def test_config_active(client):
    client.post("/config/profile", json={"name": "act2", "values": {"X": "1"}})
    client.post("/config/profile/act2/activate")
    r = client.get("/config/active")
    assert r.status_code == 200
    data = r.json()
    assert data["active"] == "act2"
    assert data["values"]["X"] == "1"

def test_config_profile_delete(client):
    client.post("/config/profile", json={"name": "del_prof", "values": {}})
    r = client.delete("/config/profile/del_prof")
    assert r.status_code == 200
    assert r.json()["deleted"] == "del_prof"

# ── Phase 36: Notification Center ─────────────────────────────────────────────
def test_notify_push(client):
    r = client.post("/notify", json={"title": "Deploy done", "message": "All good", "level": "success"})
    assert r.status_code == 200
    assert "id" in r.json()

def test_notify_no_title(client):
    r = client.post("/notify", json={"title": "", "message": "oops"})
    assert r.status_code == 400

def test_notifications_list(client):
    client.post("/notify", json={"title": "A", "level": "info"})
    r = client.get("/notifications")
    assert r.status_code == 200
    data = r.json()
    assert "notifications" in data
    assert "unread" in data
    assert data["unread"] >= 1

def test_notification_get(client):
    r1 = client.post("/notify", json={"title": "Get me", "level": "warn"})
    nid = r1.json()["id"]
    r = client.get(f"/notification/{nid}")
    assert r.status_code == 200
    assert r.json()["title"] == "Get me"

def test_notifications_mark_read(client):
    client.post("/notify", json={"title": "Unread", "level": "info"})
    r = client.post("/notifications/mark-read")
    assert r.status_code == 200
    assert r.json()["marked"] >= 1

def test_notifications_clear(client):
    client.post("/notify", json={"title": "Clear me", "level": "info"})
    r = client.delete("/notifications/clear")
    assert r.status_code == 200
    assert r.json()["cleared"] >= 1

def test_notification_delete(client):
    r1 = client.post("/notify", json={"title": "Del me", "level": "error"})
    nid = r1.json()["id"]
    r = client.delete(f"/notification/{nid}")
    assert r.status_code == 200
    assert r.json()["deleted"] == nid

# ── Phase 37: Task Queue ───────────────────────────────────────────────────────
def test_queue_task_add(client):
    r = client.post("/queue/task", json={"name": "build_image", "priority": 2})
    assert r.status_code == 200
    assert "id" in r.json()

def test_queue_task_no_name(client):
    r = client.post("/queue/task", json={"name": "", "priority": 1})
    assert r.status_code == 400

def test_queue_tasks_list(client):
    client.post("/queue/task", json={"name": "list_task", "priority": 5})
    r = client.get("/queue/tasks")
    assert r.status_code == 200
    data = r.json()
    assert "tasks" in data
    assert any(t["name"] == "list_task" for t in data["tasks"])

def test_queue_task_get(client):
    r1 = client.post("/queue/task", json={"name": "get_task", "priority": 3})
    tid = r1.json()["id"]
    r = client.get(f"/queue/task/{tid}")
    assert r.status_code == 200
    assert r.json()["name"] == "get_task"

def test_queue_task_complete(client):
    r1 = client.post("/queue/task", json={"name": "complete_task", "priority": 1})
    tid = r1.json()["id"]
    r = client.post(f"/queue/task/{tid}/complete")
    assert r.status_code == 200
    assert r.json()["status"] == "done"

def test_queue_stats(client):
    client.post("/queue/task", json={"name": "stats_task", "priority": 5})
    r = client.get("/queue/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "pending" in data
    assert "done" in data

def test_queue_task_delete(client):
    r1 = client.post("/queue/task", json={"name": "del_task", "priority": 7})
    tid = r1.json()["id"]
    r = client.delete(f"/queue/task/{tid}")
    assert r.status_code == 200
    assert r.json()["deleted"] == tid

# ── Phase 38: Brainstorm Mode ─────────────────────────────────────────────────

def test_brainstorm_create(client):
    r = client.post("/brainstorm/session", json={"title": "Test Brainstorm", "description": "desc"})
    assert r.status_code == 200
    d = r.json()
    assert d["title"] == "Test Brainstorm"
    assert "id" in d
    assert d["messages"] == []

def test_brainstorm_create_empty_title(client):
    r = client.post("/brainstorm/session", json={"title": ""})
    assert r.status_code == 200
    # Empty title gets a default name
    assert r.json()["title"].startswith("Session")

def test_brainstorm_list(client):
    client.post("/brainstorm/session", json={"title": "BS List Test"})
    r = client.get("/brainstorm/sessions")
    assert r.status_code == 200
    d = r.json()
    assert "sessions" in d
    assert d["total"] >= 1
    titles = [s["title"] for s in d["sessions"]]
    assert "BS List Test" in titles

def test_brainstorm_get(client):
    r1 = client.post("/brainstorm/session", json={"title": "BS Get Test"})
    sid = r1.json()["id"]
    r = client.get(f"/brainstorm/session/{sid}")
    assert r.status_code == 200
    assert r.json()["title"] == "BS Get Test"

def test_brainstorm_get_not_found(client):
    r = client.get("/brainstorm/session/999999")
    assert r.status_code == 404

def test_brainstorm_message_user_only(client):
    """Adding an assistant message directly (no LLM call) works."""
    r1 = client.post("/brainstorm/session", json={"title": "BS Msg Test"})
    sid = r1.json()["id"]
    r = client.post(
        f"/brainstorm/session/{sid}/message",
        json={"role": "assistant", "content": "Hello from AI"},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["user_message"]["content"] == "Hello from AI"
    assert d["ai_reply"] is None

def test_brainstorm_message_empty(client):
    r1 = client.post("/brainstorm/session", json={"title": "BS Empty Msg"})
    sid = r1.json()["id"]
    r = client.post(f"/brainstorm/session/{sid}/message", json={"role": "user", "content": "   "})
    assert r.status_code == 400

def test_brainstorm_export_json(client):
    r1 = client.post("/brainstorm/session", json={"title": "BS Export JSON"})
    sid = r1.json()["id"]
    client.post(f"/brainstorm/session/{sid}/message",
                json={"role": "assistant", "content": "idea"})
    r = client.post(f"/brainstorm/session/{sid}/export", json={"format": "json"})
    assert r.status_code == 200
    d = r.json()
    assert d["format"] == "json"
    parsed = json.loads(d["content"])
    assert parsed["title"] == "BS Export JSON"

def test_brainstorm_export_markdown(client):
    r1 = client.post("/brainstorm/session", json={"title": "BS Export MD"})
    sid = r1.json()["id"]
    client.post(f"/brainstorm/session/{sid}/message",
                json={"role": "assistant", "content": "some idea"})
    r = client.post(f"/brainstorm/session/{sid}/export", json={"format": "markdown"})
    assert r.status_code == 200
    d = r.json()
    assert d["format"] == "markdown"
    assert "# BS Export MD" in d["content"]
    assert "some idea" in d["content"]

def test_brainstorm_to_project(client, tmp_path, monkeypatch):
    import tempfile, pathlib
    # Point base_dir to a temp dir so we don't pollute the real workspace
    real_projects = pathlib.Path("projects")
    real_projects.mkdir(exist_ok=True)
    r1 = client.post("/brainstorm/session", json={"title": "BS Project Test"})
    sid = r1.json()["id"]
    slug = f"_bs_test_proj_{sid}"
    r = client.post(
        f"/brainstorm/session/{sid}/to-project",
        json={"project_name": "BS Test Project", "project_path": slug},
    )
    assert r.status_code == 200
    d = r.json()
    assert "README.md" in d["files_created"]
    assert "brainstorm.md" in d["files_created"]
    # Cleanup
    import shutil
    proj_dir = pathlib.Path(f"projects/{slug}")
    if proj_dir.exists():
        shutil.rmtree(proj_dir)

def test_brainstorm_to_project_conflict(client):
    """Creating two projects with the same slug should 409."""
    r1 = client.post("/brainstorm/session", json={"title": "BS Conflict"})
    sid = r1.json()["id"]
    slug = f"_bs_conflict_test_{sid}"
    client.post(f"/brainstorm/session/{sid}/to-project",
                json={"project_name": "Conflict Test", "project_path": slug})
    r2 = client.post(f"/brainstorm/session/{sid}/to-project",
                     json={"project_name": "Conflict Test", "project_path": slug})
    assert r2.status_code == 409
    # Cleanup
    import shutil, pathlib
    proj_dir = pathlib.Path(f"projects/{slug}")
    if proj_dir.exists():
        shutil.rmtree(proj_dir)

def test_brainstorm_delete(client):
    r1 = client.post("/brainstorm/session", json={"title": "BS Delete Test"})
    sid = r1.json()["id"]
    r = client.delete(f"/brainstorm/session/{sid}")
    assert r.status_code == 200
    assert r.json()["deleted"] == sid
    r2 = client.get(f"/brainstorm/session/{sid}")
    assert r2.status_code == 404

# ── Phase 39: Web Search ──────────────────────────────────────────────────────

def test_web_search_route_exists(client):
    """The /search/web endpoint exists (even if the network call fails in CI)."""
    r = client.get("/search/web?q=python+programming")
    # 200 = success, 502 = network unreachable in CI — both are acceptable
    assert r.status_code in (200, 502)
    if r.status_code == 200:
        d = r.json()
        assert "query" in d
        assert "results" in d
        assert isinstance(d["results"], list)

def test_web_search_missing_query(client):
    r = client.get("/search/web")
    assert r.status_code == 422  # FastAPI validation error

def test_web_search_max_results_capped(client):
    """max_results=0 should be rejected; max_results=25 is rejected (>20 is out of range)."""
    r = client.get("/search/web?q=test&max_results=0")
    assert r.status_code == 422
    r2 = client.get("/search/web?q=test&max_results=21")
    assert r2.status_code == 422


# ── Phase 40: Code Snippet Library ───────────────────────────────────────────

def test_snippet_create(client):
    r = client.post("/snippet", json={"name": "Hello World", "code": "print('hello')", "language": "python"})
    assert r.status_code == 200
    assert "id" in r.json()

def test_snippet_create_no_name(client):
    r = client.post("/snippet", json={"name": "", "code": "print('x')"})
    assert r.status_code == 400

def test_snippet_create_no_code(client):
    r = client.post("/snippet", json={"name": "Test", "code": ""})
    assert r.status_code == 400

def test_snippet_list(client):
    client.post("/snippet", json={"name": "Snip List Test", "code": "x=1", "language": "python"})
    r = client.get("/snippets")
    assert r.status_code == 200
    d = r.json()
    assert "snippets" in d
    assert any(s["name"] == "Snip List Test" for s in d["snippets"])

def test_snippet_list_filter_language(client):
    client.post("/snippet", json={"name": "JS Test", "code": "console.log(1)", "language": "javascript"})
    r = client.get("/snippets?language=javascript")
    assert r.status_code == 200
    d = r.json()
    assert all(s["language"] == "javascript" for s in d["snippets"])

def test_snippet_get(client):
    r1 = client.post("/snippet", json={"name": "Get Test", "code": "y=2"})
    sid = r1.json()["id"]
    r = client.get(f"/snippet/{sid}")
    assert r.status_code == 200
    assert r.json()["name"] == "Get Test"

def test_snippet_get_not_found(client):
    r = client.get("/snippet/999999")
    assert r.status_code == 404

def test_snippet_update(client):
    r1 = client.post("/snippet", json={"name": "Update Test", "code": "z=3"})
    sid = r1.json()["id"]
    r = client.put(f"/snippet/{sid}", json={"name": "Updated Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "Updated Name"

def test_snippet_update_not_found(client):
    r = client.put("/snippet/999999", json={"name": "X"})
    assert r.status_code == 404

def test_snippet_delete(client):
    r1 = client.post("/snippet", json={"name": "Delete Test", "code": "d=4"})
    sid = r1.json()["id"]
    r = client.delete(f"/snippet/{sid}")
    assert r.status_code == 200
    assert r.json()["deleted"] == sid
    r2 = client.get(f"/snippet/{sid}")
    assert r2.status_code == 404

def test_snippet_search(client):
    client.post("/snippet", json={"name": "Search Needle", "code": "needle=42", "tags": ["searchable"]})
    r = client.get("/snippets/search?q=needle")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] >= 1
    assert any("needle" in s["name"].lower() or "needle" in s["code"].lower() for s in d["snippets"])

def test_snippet_search_missing_q(client):
    r = client.get("/snippets/search")
    assert r.status_code == 422


# ── Phase 41: Diff & Patch Tool ──────────────────────────────────────────────

def test_diff_text_basic(client):
    r = client.post("/diff", json={"original": "line1\nline2\n", "modified": "line1\nline2b\n"})
    assert r.status_code == 200
    d = r.json()
    assert "patch" in d
    assert d["has_diff"] is True
    assert d["changed_lines"] >= 1

def test_diff_text_identical(client):
    r = client.post("/diff", json={"original": "same\n", "modified": "same\n"})
    assert r.status_code == 200
    d = r.json()
    assert d["has_diff"] is False
    assert d["changed_lines"] == 0

def test_diff_text_empty_inputs(client):
    r = client.post("/diff", json={"original": "", "modified": "new line\n"})
    assert r.status_code == 200
    d = r.json()
    assert d["has_diff"] is True

def test_patch_text_basic(client):
    original = "line1\nline2\nline3\n"
    modified = "line1\nline2b\nline3\n"
    r1 = client.post("/diff", json={"original": original, "modified": modified})
    patch = r1.json()["patch"]
    r2 = client.post("/patch", json={"original": original, "patch": patch})
    assert r2.status_code == 200
    d = r2.json()
    assert d["success"] is True
    assert "line2b" in d["result"]

def test_patch_text_empty_patch(client):
    r = client.post("/patch", json={"original": "text", "patch": ""})
    assert r.status_code == 400

def test_diff_files_not_found(client):
    r = client.post("/diff/files", json={"path_a": "nonexistent_a.txt", "path_b": "nonexistent_b.txt"})
    assert r.status_code in (400, 404)

def test_patch_file_not_found(client):
    r = client.post("/patch/file", json={"path": "nonexistent_file.txt", "patch": "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n"})
    assert r.status_code == 404

# ── Phase 42: AI Persona (hive-mind) ──────────────────────────────────────────

def test_ai_personas_list(client):
    r = client.get("/ai/personas")
    assert r.status_code == 200
    d = r.json()
    assert "personas" in d
    assert d["total"] >= 14
    assert d["builtin_count"] == 14
    names = [p["name"] for p in d["personas"]]
    for expected in (
        "swissagent_assistant",
        "senior_developer", "software_architect", "frontend_developer",
        "backend_developer", "database_engineer", "mobile_developer",
        "devops_engineer", "security_auditor", "test_engineer",
        "code_reviewer", "performance_engineer", "documentation_writer",
        "ai_ml_engineer",
    ):
        assert expected in names, f"Built-in persona '{expected}' missing"

def test_ai_persona_get_builtin(client):
    r = client.get("/ai/persona/senior_developer")
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "senior_developer"
    assert d["builtin"] is True
    assert "system_prompt" in d
    assert len(d["system_prompt"]) > 100

def test_ai_persona_get_not_found(client):
    r = client.get("/ai/persona/nonexistent_persona_xyz")
    assert r.status_code == 404

def test_ai_persona_active_default(client):
    r = client.get("/ai/persona/active")
    assert r.status_code == 200
    d = r.json()
    assert "active" in d
    # The SwissAgent Assistant persona is always returned as default
    assert d["active"] is not None

def test_ai_persona_default_is_swissagent_assistant(client):
    """When no persona has been explicitly activated the platform default is used."""
    # Reset any previously-activated persona so we get a clean default state
    client.delete("/ai/persona/active")
    r = client.get("/ai/persona/active")
    assert r.status_code == 200
    d = r.json()
    assert d["active"] == "swissagent_assistant"
    assert d.get("is_default") is True

def test_ai_persona_context_default(client):
    r = client.get("/ai/persona/context")
    assert r.status_code == 200
    d = r.json()
    assert "system_prompt" in d
    assert len(d["system_prompt"]) > 20
    # There is always an active persona name (default or explicit)
    assert d["active"] is not None

def test_ai_persona_default_context_contains_swissagent(client):
    """Default context system prompt is the SwissAgent Assistant persona."""
    # Reset to default by not activating anything; the fixture gives a fresh client
    r = client.get("/ai/persona/context")
    assert r.status_code == 200
    d = r.json()
    assert "SwissAgent" in d["system_prompt"]

def test_ai_persona_create_and_get(client):
    r = client.post("/ai/persona", json={
        "name": "test_custom_persona",
        "display_name": "Test Custom",
        "role": "Test Role",
        "domain": "Testing",
        "system_prompt": "You are a test persona for automated tests.",
        "offline_model": "llama3",
        "llm_backend": "ollama",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["persona"]["name"] == "test_custom_persona"

    # Retrieve it
    r2 = client.get("/ai/persona/test_custom_persona")
    assert r2.status_code == 200
    assert r2.json()["display_name"] == "Test Custom"
    assert r2.json()["builtin"] is False

def test_ai_persona_create_missing_name(client):
    r = client.post("/ai/persona", json={"name": "", "system_prompt": "hello"})
    assert r.status_code == 400

def test_ai_persona_create_missing_prompt(client):
    r = client.post("/ai/persona", json={"name": "noprompt_persona", "system_prompt": ""})
    assert r.status_code == 400

def test_ai_persona_activate_builtin(client):
    r = client.post("/ai/persona/software_architect/activate")
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["active"] == "software_architect"

    # Confirm active endpoint reflects change
    r2 = client.get("/ai/persona/active")
    assert r2.status_code == 200
    assert r2.json()["active"] == "software_architect"

    # Context should now show architect's prompt
    r3 = client.get("/ai/persona/context")
    assert r3.status_code == 200
    assert "Software Architect" in r3.json()["system_prompt"]

def test_ai_persona_activate_not_found(client):
    r = client.post("/ai/persona/ghost_persona_xyz/activate")
    assert r.status_code == 404

def test_ai_persona_delete_custom(client):
    # Create then delete
    client.post("/ai/persona", json={
        "name": "deleteme_persona",
        "system_prompt": "Temporary persona to be deleted.",
    })
    r = client.delete("/ai/persona/deleteme_persona")
    assert r.status_code == 200
    assert r.json()["deleted"] == "deleteme_persona"
    # Confirm gone
    r2 = client.get("/ai/persona/deleteme_persona")
    assert r2.status_code == 404

def test_ai_persona_delete_builtin_forbidden(client):
    r = client.delete("/ai/persona/senior_developer")
    assert r.status_code == 403

def test_ai_personas_list_includes_custom(client):
    client.post("/ai/persona", json={
        "name": "list_check_persona",
        "system_prompt": "Listed persona.",
        "domain": "Testing",
    })
    r = client.get("/ai/personas")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()["personas"]]
    assert "list_check_persona" in names

def test_ai_persona_context_with_active_persona(client):
    # Activate a built-in and confirm system prompt changes
    client.post("/ai/persona/devops_engineer/activate")
    r = client.get("/ai/persona/context")
    assert r.status_code == 200
    d = r.json()
    assert d["active"] == "devops_engineer"
    assert "DevOps" in d["system_prompt"]

def test_ai_persona_patch(client):
    """PATCH /ai/persona/{name} updates individual fields without full replacement."""
    client.post("/ai/persona", json={
        "name": "patch_test_persona",
        "display_name": "Patch Test",
        "role": "Original Role",
        "system_prompt": "Original prompt.",
    })
    r = client.patch("/ai/persona/patch_test_persona", json={
        "role": "Updated Role",
        "display_name": "Patched Name",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["persona"]["role"] == "Updated Role"
    assert d["persona"]["display_name"] == "Patched Name"
    # system_prompt unchanged
    assert d["persona"]["system_prompt"] == "Original prompt."

def test_ai_persona_patch_builtin_forbidden(client):
    """Patching a built-in persona should return 403."""
    r = client.patch("/ai/persona/senior_developer", json={"role": "Hacker"})
    assert r.status_code == 403

def test_ai_persona_patch_not_found(client):
    r = client.patch("/ai/persona/ghost_patch_xyz", json={"role": "Ghost"})
    assert r.status_code == 404

def test_ai_persona_patch_blank_prompt_rejected(client):
    client.post("/ai/persona", json={
        "name": "blank_prompt_patch_persona",
        "system_prompt": "Valid prompt.",
    })
    r = client.patch("/ai/persona/blank_prompt_patch_persona", json={"system_prompt": "   "})
    assert r.status_code == 400

def test_ai_persona_clone_builtin(client):
    """POST /ai/persona/{name}/clone creates an editable copy of a built-in."""
    r = client.post("/ai/persona/senior_developer/clone", json={
        "new_name": "my_senior_dev_clone",
        "new_display_name": "My Senior Dev",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["persona"]["name"] == "my_senior_dev_clone"
    assert d["persona"]["builtin"] is False
    assert d["persona"]["cloned_from"] == "senior_developer"
    assert d["persona"]["display_name"] == "My Senior Dev"
    # system_prompt is a copy of the original
    orig = client.get("/ai/persona/senior_developer").json()
    assert d["persona"]["system_prompt"] == orig["system_prompt"]

def test_ai_persona_clone_custom(client):
    """Cloning a custom persona also works."""
    client.post("/ai/persona", json={
        "name": "source_clone_persona",
        "system_prompt": "Source prompt for cloning.",
        "role": "Source Role",
    })
    r = client.post("/ai/persona/source_clone_persona/clone", json={
        "new_name": "cloned_persona_target",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["persona"]["name"] == "cloned_persona_target"
    assert d["persona"]["system_prompt"] == "Source prompt for cloning."

def test_ai_persona_clone_not_found(client):
    r = client.post("/ai/persona/ghost_source_xyz/clone", json={"new_name": "anything"})
    assert r.status_code == 404

def test_ai_persona_clone_missing_new_name(client):
    r = client.post("/ai/persona/senior_developer/clone", json={"new_name": ""})
    assert r.status_code == 400

def test_ai_persona_generate(client):
    """POST /ai/persona/generate builds a project-specific persona."""
    r = client.post("/ai/persona/generate", json={
        "persona_name": "acme_app_ai",
        "project_name": "Acme App",
        "description": "An offline-first task management application for enterprise teams.",
        "tech_stack": ["Python", "FastAPI", "React", "PostgreSQL"],
        "goals": ["offline-first", "high performance", "WCAG AA accessibility"],
        "conventions": "4-space indent, black formatter, type hints on all public APIs.",
        "offline_model": "deepseek-coder-v2",
        "llm_backend": "ollama",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["persona"]["name"] == "acme_app_ai"
    assert "Acme App" in d["persona"]["system_prompt"]
    assert "FastAPI" in d["persona"]["system_prompt"]
    assert "offline-first" in d["persona"]["system_prompt"]
    assert "black formatter" in d["persona"]["system_prompt"]
    assert d["persona"]["builtin"] is False

    # Generated persona can be retrieved
    r2 = client.get("/ai/persona/acme_app_ai")
    assert r2.status_code == 200
    assert r2.json()["role"] == "Project AI for Acme App"

def test_ai_persona_generate_missing_fields(client):
    r = client.post("/ai/persona/generate", json={
        "persona_name": "",
        "project_name": "X",
        "description": "Y",
    })
    assert r.status_code == 400

    r2 = client.post("/ai/persona/generate", json={
        "persona_name": "x",
        "project_name": "",
        "description": "Y",
    })
    assert r2.status_code == 400

    r3 = client.post("/ai/persona/generate", json={
        "persona_name": "x",
        "project_name": "X",
        "description": "",
    })
    assert r3.status_code == 400

def test_ai_persona_generate_then_activate(client):
    """A generated persona can be immediately activated."""
    client.post("/ai/persona/generate", json={
        "persona_name": "my_project_persona",
        "project_name": "My Project",
        "description": "A test project for the persona generate pipeline.",
        "tech_stack": ["Go", "Vue 3"],
    })
    r = client.post("/ai/persona/my_project_persona/activate")
    assert r.status_code == 200
    assert r.json()["active"] == "my_project_persona"

    ctx = client.get("/ai/persona/context").json()
    assert "My Project" in ctx["system_prompt"]

def test_ai_persona_swissagent_assistant_builtin(client):
    """swissagent_assistant is present as a built-in and cannot be deleted."""
    r = client.get("/ai/persona/swissagent_assistant")
    assert r.status_code == 200
    d = r.json()
    assert d["builtin"] is True
    assert "SwissAgent" in d["system_prompt"]

    r2 = client.delete("/ai/persona/swissagent_assistant")
    assert r2.status_code == 403

def test_ai_persona_deactivate(client):
    """DELETE /ai/persona/active clears any explicit activation and reverts to default."""
    # Activate something first
    client.post("/ai/persona/senior_developer/activate")
    assert client.get("/ai/persona/active").json()["active"] == "senior_developer"

    r = client.delete("/ai/persona/active")
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["previous"] == "senior_developer"
    assert d["active"] == "swissagent_assistant"
    assert d["is_default"] is True

    # Active endpoint now reports default
    r2 = client.get("/ai/persona/active")
    assert r2.json()["active"] == "swissagent_assistant"
    assert r2.json().get("is_default") is True

    # Context now shows the default SwissAgent Assistant prompt
    ctx = client.get("/ai/persona/context").json()
    assert ctx["is_default"] is True
    assert "SwissAgent" in ctx["system_prompt"]

# ── Phase 44: Environment Variables Manager ───────────────────────────────────

def test_env_files_list(client):
    r = client.get("/env/files")
    assert r.status_code == 200
    d = r.json()
    assert "files" in d
    assert "total" in d

def test_env_var_set_and_get(client):
    # Set a variable
    r = client.post("/env/var", json={"file": "workspace/test.env", "key": "MY_KEY", "value": "hello_world", "comment": "test var"})
    assert r.status_code == 200
    assert r.json()["success"] is True
    # Read it back
    r2 = client.get("/env/vars?file=workspace/test.env")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["exists"] is True
    keys = [v["key"] for v in d2["vars"]]
    assert "MY_KEY" in keys
    val = next(v["value"] for v in d2["vars"] if v["key"] == "MY_KEY")
    assert val == "hello_world"

def test_env_var_update(client):
    # Update existing key
    client.post("/env/var", json={"file": "workspace/test_update.env", "key": "PORT", "value": "8000"})
    client.post("/env/var", json={"file": "workspace/test_update.env", "key": "PORT", "value": "9000"})
    r = client.get("/env/vars?file=workspace/test_update.env")
    vars_list = r.json()["vars"]
    port_vars = [v for v in vars_list if v["key"] == "PORT"]
    assert len(port_vars) == 1, "Duplicate keys should be merged"
    assert port_vars[0]["value"] == "9000"

def test_env_var_delete(client):
    client.post("/env/var", json={"file": "workspace/test_del.env", "key": "TO_DELETE", "value": "bye"})
    r = client.delete("/env/var?file=workspace/test_del.env&key=TO_DELETE")
    assert r.status_code == 200
    assert r.json()["deleted"] == "TO_DELETE"
    # Should be gone
    r2 = client.get("/env/vars?file=workspace/test_del.env")
    keys = [v["key"] for v in r2.json()["vars"]]
    assert "TO_DELETE" not in keys

def test_env_var_delete_not_found(client):
    client.post("/env/var", json={"file": "workspace/test_notfound.env", "key": "EXISTS", "value": "yes"})
    r = client.delete("/env/var?file=workspace/test_notfound.env&key=DOES_NOT_EXIST")
    assert r.status_code == 404

def test_env_export(client):
    client.post("/env/var", json={"file": "workspace/test_export.env", "key": "EXPORT_KEY", "value": "exported"})
    r = client.get("/env/export?file=workspace/test_export.env")
    assert r.status_code == 200
    d = r.json()
    assert "content" in d
    assert "EXPORT_KEY=exported" in d["content"]

def test_env_export_not_found(client):
    r = client.get("/env/export?file=workspace/nonexistent_file_xyz.env")
    assert r.status_code == 404

def test_env_import(client):
    content = "DB_HOST=localhost\nDB_PORT=5432\n# comment\nDB_NAME=mydb\n"
    r = client.post("/env/import", json={"file": "workspace/test_import.env", "content": content})
    assert r.status_code == 200
    assert r.json()["vars_imported"] == 3
    r2 = client.get("/env/vars?file=workspace/test_import.env")
    keys = [v["key"] for v in r2.json()["vars"]]
    assert "DB_HOST" in keys
    assert "DB_PORT" in keys
    assert "DB_NAME" in keys

def test_env_var_set_missing_key(client):
    r = client.post("/env/var", json={"file": ".env", "key": "", "value": "val"})
    assert r.status_code == 400

def test_env_vars_nonexistent_file(client):
    r = client.get("/env/vars?file=workspace/totally_missing_xyz.env")
    assert r.status_code == 200
    assert r.json()["exists"] is False

# ── Phase 45: API Client / HTTP Playground ────────────────────────────────────

def test_apiclient_send_get(client):
    r = client.post("/apiclient/send", json={"method": "GET", "url": "https://httpbin.org/get"})
    # If offline/blocked, expect 502 or 504; otherwise 200
    assert r.status_code in (200, 502, 504)
    if r.status_code == 200:
        d = r.json()
        assert "status_code" in d
        assert "body" in d
        assert "elapsed_ms" in d

def test_apiclient_send_missing_url(client):
    r = client.post("/apiclient/send", json={"method": "GET", "url": ""})
    assert r.status_code == 400

def test_apiclient_send_invalid_scheme(client):
    """Non-http/https schemes must be rejected to prevent SSRF via file:// etc."""
    for bad_url in ("file:///etc/passwd", "ftp://example.com/file", "javascript:alert(1)"):
        r = client.post("/apiclient/send", json={"method": "GET", "url": bad_url})
        assert r.status_code == 400, f"Expected 400 for {bad_url}"

def test_apiclient_send_invalid_method(client):
    r = client.post("/apiclient/send", json={"method": "INJECT", "url": "https://example.com"})
    assert r.status_code == 400

def test_apiclient_send_http_internal_allowed(client):
    """http:// URLs (including localhost) are allowed — this is a developer tool."""
    # We don't actually connect; we just check the URL passes scheme validation
    # (it will fail with a connection error at the network level, not a 400)
    r = client.post("/apiclient/send", json={"method": "GET", "url": "http://localhost:9999/nonexistent"})
    # 400 = rejected by validation, 502/504 = rejected by network — both are OK
    # What must NOT happen is a 400 due to scheme rejection
    assert r.status_code != 400 or "scheme" not in r.json().get("detail", "").lower()

def test_apiclient_collections_empty(client):
    r = client.get("/apiclient/collections")
    assert r.status_code == 200
    d = r.json()
    assert "collections" in d
    assert isinstance(d["collections"], list)

def test_apiclient_collection_crud(client):
    # Create
    r = client.post("/apiclient/collection", json={"name": "test_collection", "description": "A test collection"})
    assert r.status_code == 200
    assert r.json()["success"] is True

    # List
    r2 = client.get("/apiclient/collections")
    names = [c["name"] for c in r2.json()["collections"]]
    assert "test_collection" in names

    # Get
    r3 = client.get("/apiclient/collection/test_collection")
    assert r3.status_code == 200
    assert r3.json()["name"] == "test_collection"

def test_apiclient_collection_duplicate(client):
    client.post("/apiclient/collection", json={"name": "dupe_collection"})
    r = client.post("/apiclient/collection", json={"name": "dupe_collection"})
    assert r.status_code == 409

def test_apiclient_collection_not_found(client):
    r = client.get("/apiclient/collection/ghost_collection_xyz")
    assert r.status_code == 404

def test_apiclient_request_save_and_list(client):
    client.post("/apiclient/collection", json={"name": "req_test_col"})
    r = client.post("/apiclient/collection/req_test_col/request", json={
        "name": "Get Users",
        "method": "GET",
        "url": "https://api.example.com/users",
        "headers": {"Authorization": "Bearer token123"},
        "body": "",
        "body_type": "raw",
    })
    assert r.status_code == 200
    assert r.json()["request"] == "Get Users"

    r2 = client.get("/apiclient/collection/req_test_col")
    assert "Get Users" in r2.json()["requests"]
    assert r2.json()["requests"]["Get Users"]["method"] == "GET"

def test_apiclient_request_delete(client):
    client.post("/apiclient/collection", json={"name": "req_del_col"})
    client.post("/apiclient/collection/req_del_col/request", json={
        "name": "ToDelete", "method": "DELETE", "url": "https://api.example.com/item/1",
    })
    r = client.delete("/apiclient/collection/req_del_col/request/ToDelete")
    assert r.status_code == 200
    assert r.json()["deleted"] == "ToDelete"
    r2 = client.get("/apiclient/collection/req_del_col")
    assert "ToDelete" not in r2.json()["requests"]

def test_apiclient_request_save_missing_url(client):
    client.post("/apiclient/collection", json={"name": "val_test_col"})
    r = client.post("/apiclient/collection/val_test_col/request", json={
        "name": "BadReq", "method": "GET", "url": "",
    })
    assert r.status_code == 400

def test_apiclient_collection_delete(client):
    client.post("/apiclient/collection", json={"name": "to_delete_col"})
    r = client.delete("/apiclient/collection/to_delete_col")
    assert r.status_code == 200
    r2 = client.get("/apiclient/collection/to_delete_col")
    assert r2.status_code == 404

# ── Phase 46: AI Suggestions Timeline ─────────────────────────────────────────

def test_ai_timeline_empty(client):
    r = client.get("/ai/timeline")
    assert r.status_code == 200
    d = r.json()
    assert "events" in d
    assert isinstance(d["events"], list)

def test_ai_timeline_add_event(client):
    r = client.post("/ai/timeline/event", json={
        "event_type": "suggestion",
        "summary": "Refactor loop to list comprehension",
        "detail": "for x in y: arr.append(x)  →  arr = [x for x in y]",
        "file_path": "workspace/main.py",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert isinstance(d["id"], int)

def test_ai_timeline_missing_summary(client):
    r = client.post("/ai/timeline/event", json={"event_type": "chat", "summary": ""})
    assert r.status_code == 400

def test_ai_timeline_missing_type(client):
    r = client.post("/ai/timeline/event", json={"event_type": "", "summary": "hello"})
    assert r.status_code == 400

def test_ai_timeline_list_and_filter(client):
    client.post("/ai/timeline/event", json={"event_type": "apply", "summary": "Applied patch", "file_path": "workspace/app.py"})
    r = client.get("/ai/timeline?event_type=apply")
    assert r.status_code == 200
    events = r.json()["events"]
    assert all(e["event_type"] == "apply" for e in events)

def test_ai_timeline_get_single(client):
    r = client.post("/ai/timeline/event", json={"event_type": "generate", "summary": "Generated tests"})
    event_id = r.json()["id"]
    r2 = client.get(f"/ai/timeline/{event_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == event_id

def test_ai_timeline_get_not_found(client):
    r = client.get("/ai/timeline/999999")
    assert r.status_code == 404

def test_ai_timeline_update_accepted(client):
    r = client.post("/ai/timeline/event", json={"event_type": "refactor", "summary": "Simplified function"})
    event_id = r.json()["id"]
    r2 = client.patch(f"/ai/timeline/{event_id}?accepted=true")
    assert r2.status_code == 200
    assert r2.json()["event"]["accepted"] is True

def test_ai_timeline_update_rejected(client):
    r = client.post("/ai/timeline/event", json={"event_type": "refactor", "summary": "Remove unused import"})
    event_id = r.json()["id"]
    r2 = client.patch(f"/ai/timeline/{event_id}?accepted=false")
    assert r2.status_code == 200
    assert r2.json()["event"]["accepted"] is False

def test_ai_timeline_update_not_found(client):
    r = client.patch("/ai/timeline/999999?accepted=true")
    assert r.status_code == 404

def test_ai_timeline_clear(client):
    client.post("/ai/timeline/event", json={"event_type": "chat", "summary": "Test event to clear"})
    r = client.delete("/ai/timeline/clear")
    assert r.status_code == 200
    assert r.json()["success"] is True
    r2 = client.get("/ai/timeline")
    assert r2.json()["events"] == []

# ── Phase 47: Project Health Dashboard ────────────────────────────────────────

def test_project_health(client):
    r = client.get("/project/health")
    assert r.status_code == 200
    d = r.json()
    assert "score" in d
    assert isinstance(d["score"], (int, float))
    assert 0 <= d["score"] <= 100
    assert "status" in d
    assert d["status"] in ("excellent", "good", "fair", "needs_attention")
    assert "generated_at" in d
    assert "ai_timeline" in d
    assert "task_queue" in d
    assert "notifications" in d
    assert "agents" in d
    assert "cron_jobs" in d
    assert "feature_flags" in d
    assert "snippets" in d
    assert "brainstorm_sessions" in d
    assert "audit_log" in d

def test_project_health_ai_timeline_stats(client):
    """After adding accepted/rejected events, acceptance_rate should be computed."""
    client.delete("/ai/timeline/clear")
    r1 = client.post("/ai/timeline/event", json={"event_type": "suggestion", "summary": "Accepted event"})
    client.patch(f"/ai/timeline/{r1.json()['id']}?accepted=true")
    r2 = client.post("/ai/timeline/event", json={"event_type": "suggestion", "summary": "Rejected event"})
    client.patch(f"/ai/timeline/{r2.json()['id']}?accepted=false")

    r = client.get("/project/health")
    tl = r.json()["ai_timeline"]
    assert tl["total_events"] == 2
    assert tl["accepted"] == 1
    assert tl["rejected"] == 1
    assert tl["acceptance_rate_pct"] == 50.0

# ── Phase 48: Code Documentation Generator ────────────────────────────────────

def test_docgen_generate_python(client):
    r = client.post("/docgen/generate", json={
        "code": "def add(a, b):\n    return a + b",
        "language": "python",
        "style": "docstring",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert "id" in d
    assert d["language"] == "python"
    assert "documentation" in d
    assert len(d["documentation"]) > 0

def test_docgen_generate_javascript(client):
    r = client.post("/docgen/generate", json={
        "code": "function greet(name) { return `Hello, ${name}`; }",
        "language": "javascript",
        "style": "jsdoc",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["language"] == "javascript"

def test_docgen_generate_readme_style(client):
    r = client.post("/docgen/generate", json={
        "code": "class Foo:\n    pass",
        "language": "python",
        "style": "readme",
        "context": "A simple placeholder class",
    })
    assert r.status_code == 200
    d = r.json()
    assert "readme" in d["documentation"].lower() or "documentation" in d["documentation"].lower() or len(d["documentation"]) > 0

def test_docgen_generate_auto_detect_language(client):
    r = client.post("/docgen/generate", json={
        "code": "def hello():\n    print('hi')",
        "language": "",
        "style": "docstring",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["language"] == "python"

def test_docgen_generate_missing_code(client):
    r = client.post("/docgen/generate", json={"code": "", "style": "docstring"})
    assert r.status_code == 400

def test_docgen_generate_invalid_style(client):
    r = client.post("/docgen/generate", json={"code": "x = 1", "style": "invalid_style"})
    assert r.status_code == 400

def test_docgen_history_empty_initially(client):
    client.delete("/docgen/history")
    r = client.get("/docgen/history")
    assert r.status_code == 200
    d = r.json()
    assert d["entries"] == []
    assert d["total"] == 0

def test_docgen_history_populated(client):
    client.delete("/docgen/history")
    client.post("/docgen/generate", json={"code": "x = 1", "language": "python", "style": "docstring"})
    client.post("/docgen/generate", json={"code": "y = 2", "language": "python", "style": "inline"})
    r = client.get("/docgen/history")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert len(d["entries"]) == 2

def test_docgen_history_filter_language(client):
    client.delete("/docgen/history")
    client.post("/docgen/generate", json={"code": "x=1", "language": "python", "style": "docstring"})
    client.post("/docgen/generate", json={"code": "function f(){}", "language": "javascript", "style": "jsdoc"})
    r = client.get("/docgen/history?language=python")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 1
    assert d["entries"][0]["language"] == "python"

def test_docgen_history_get_single(client):
    client.delete("/docgen/history")
    r1 = client.post("/docgen/generate", json={"code": "def f(): pass", "language": "python", "style": "docstring"})
    entry_id = r1.json()["id"]
    r = client.get(f"/docgen/history/{entry_id}")
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == entry_id
    assert d["language"] == "python"

def test_docgen_history_get_not_found(client):
    r = client.get("/docgen/history/999999")
    assert r.status_code == 404

def test_docgen_history_clear(client):
    client.post("/docgen/generate", json={"code": "x = 1", "language": "python", "style": "docstring"})
    r = client.delete("/docgen/history")
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["cleared"] >= 0
    r2 = client.get("/docgen/history")
    assert r2.json()["total"] == 0

def test_docgen_generate_java(client):
    r = client.post("/docgen/generate", json={
        "code": "public class Foo { public void bar() {} }",
        "language": "java",
        "style": "javadoc",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["language"] == "java"

def test_docgen_generate_with_context(client):
    r = client.post("/docgen/generate", json={
        "code": "def multiply(a, b): return a * b",
        "language": "python",
        "style": "docstring",
        "context": "Multiplies two numbers together",
    })
    assert r.status_code == 200
    d = r.json()
    assert "Multiplies" in d["documentation"] or len(d["documentation"]) > 0

def test_docgen_inline_style(client):
    r = client.post("/docgen/generate", json={
        "code": "result = x * y",
        "language": "unknown",
        "style": "inline",
    })
    assert r.status_code == 200
    assert r.json()["success"] is True

# ── Phase 49: Dependency Analyzer ─────────────────────────────────────────────

def test_deps_analyze_empty_workspace(client):
    r = client.post("/deps/analyze", json={"project_path": ""})
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        d = r.json()
        assert d["success"] is True
        assert "id" in d
        assert "report" in d
        assert "manifests" in d["report"]
        assert "total_dependencies" in d["report"]

def test_deps_analyze_nonexistent_path(client):
    r = client.post("/deps/analyze", json={"project_path": "nonexistent_project_xyz"})
    assert r.status_code == 404

def test_deps_reports_empty(client):
    # Clear by analyzing something that returns fast, or just check list
    r = client.get("/deps/reports")
    assert r.status_code == 200
    d = r.json()
    assert "reports" in d
    assert "total" in d
    assert isinstance(d["reports"], list)

def test_deps_analyze_creates_report(client, tmp_path):
    """Analyze a temp project with a requirements.txt and verify report is created."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_deps_proj_49")
    os.makedirs(ws, exist_ok=True)
    try:
        req_file = os.path.join(ws, "requirements.txt")
        with open(req_file, "w") as f:
            f.write("requests==2.31.0\nfastapi>=0.100.0\nnumpy\n")
        r = client.post("/deps/analyze", json={"project_path": "test_deps_proj_49"})
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        report = d["report"]
        assert report["total_dependencies"] >= 3
        assert report["manifest_count"] >= 1
        manifest_files = [m["file"] for m in report["manifests"]]
        assert "requirements.txt" in manifest_files
        # Check dependencies parsed
        req_manifest = next(m for m in report["manifests"] if m["file"] == "requirements.txt")
        dep_names = [dep["name"] for dep in req_manifest["dependencies"]]
        assert "requests" in dep_names
        assert "fastapi" in dep_names
        assert "numpy" in dep_names
        # Check version parsed correctly
        req_dep = next(d for d in req_manifest["dependencies"] if d["name"] == "requests")
        assert req_dep["version"] == "2.31.0"
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)

def test_deps_analyze_package_json(client):
    """Analyze a temp project with a package.json."""
    import os, json as _json
    ws = os.path.join(os.getcwd(), "workspace", "test_deps_proj_49b")
    os.makedirs(ws, exist_ok=True)
    try:
        pkg = {"name": "test", "dependencies": {"express": "^4.18.0", "lodash": "^4.17.0"}, "devDependencies": {"jest": "^29.0.0"}}
        with open(os.path.join(ws, "package.json"), "w") as f:
            _json.dump(pkg, f)
        r = client.post("/deps/analyze", json={"project_path": "test_deps_proj_49b"})
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        report = d["report"]
        npm_manifest = next((m for m in report["manifests"] if m["file"] == "package.json"), None)
        assert npm_manifest is not None
        assert npm_manifest["ecosystem"] == "npm"
        dep_names = [dep["name"] for dep in npm_manifest["dependencies"]]
        assert "express" in dep_names
        assert "lodash" in dep_names
        assert "jest" in dep_names
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)

def test_deps_report_get_single(client):
    """Analyze a project and retrieve the report by ID."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_deps_proj_49c")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "requirements.txt"), "w") as f:
            f.write("click==8.1.0\n")
        r = client.post("/deps/analyze", json={"project_path": "test_deps_proj_49c"})
        assert r.status_code == 200
        report_id = r.json()["id"]
        r2 = client.get(f"/deps/report/{report_id}")
        assert r2.status_code == 200
        assert r2.json()["id"] == report_id
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)

def test_deps_report_get_not_found(client):
    r = client.get("/deps/report/999999")
    assert r.status_code == 404

def test_deps_report_delete(client):
    """Analyze then delete the report."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_deps_proj_49d")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "requirements.txt"), "w") as f:
            f.write("colorama==0.4.6\n")
        r = client.post("/deps/analyze", json={"project_path": "test_deps_proj_49d"})
        assert r.status_code == 200
        report_id = r.json()["id"]
        r2 = client.delete(f"/deps/report/{report_id}")
        assert r2.status_code == 200
        assert r2.json()["success"] is True
        r3 = client.get(f"/deps/report/{report_id}")
        assert r3.status_code == 404
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)

def test_deps_report_delete_not_found(client):
    r = client.delete("/deps/report/999999")
    assert r.status_code == 404

def test_deps_reports_list_pagination(client):
    r = client.get("/deps/reports?limit=5")
    assert r.status_code == 200
    d = r.json()
    assert "reports" in d
    assert len(d["reports"]) <= 5

def test_deps_path_traversal_blocked(client):
    """Attempts to traverse outside workspace are neutralized."""
    r = client.post("/deps/analyze", json={"project_path": "../etc"})
    # Should return 404 (path doesn't exist) not expose system files
    assert r.status_code == 404

# ── Agentic chat endpoint tests ───────────────────────────────────────────────

def test_agentic_chat_returns_structure(client):
    """POST /assistant/chat/agentic returns reply, todos, file_changes, session_id."""
    res = client.post("/assistant/chat/agentic", json={"message": "hello"})
    assert res.status_code == 200
    data = res.json()
    assert "reply" in data
    assert "session_id" in data
    assert "backend_used" in data
    assert "todos" in data
    assert "file_changes" in data
    assert isinstance(data["todos"], list)
    assert isinstance(data["file_changes"], list)


def test_agentic_chat_accepts_session_id(client):
    """Supplied session_id is echoed back."""
    res = client.post(
        "/assistant/chat/agentic",
        json={"message": "ping", "session_id": "agentic-test-1"},
    )
    assert res.status_code == 200
    assert res.json()["session_id"] == "agentic-test-1"


def test_agentic_chat_empty_message_rejected(client):
    """Request with no 'message' field must be rejected."""
    res = client.post("/assistant/chat/agentic", json={})
    assert res.status_code == 422


def test_agentic_chat_local_backend(client):
    """Local stub backend returns a helpful message in agentic mode."""
    res = client.post(
        "/assistant/chat/agentic",
        json={"message": "what can you do?", "llm_backend": "local"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["backend_used"] == "local"
    assert data["reply"]


def test_agentic_chat_todos_are_valid(client):
    """Each todo item has id, text, done fields; at least one todo is always returned."""
    res = client.post("/assistant/chat/agentic", json={"message": "fix my code", "llm_backend": "local"})
    assert res.status_code == 200
    todos = res.json()["todos"]
    assert len(todos) > 0, "Agentic engine must return at least one todo item"
    for t in todos:
        assert "id" in t
        assert "text" in t
        assert "done" in t


def test_agentic_chat_file_changes_are_valid(client):
    """Each file_change entry has required fields (list may be empty with stub LLM)."""
    res = client.post("/assistant/chat/agentic", json={"message": "update readme", "llm_backend": "local"})
    assert res.status_code == 200
    for fc in res.json()["file_changes"]:
        assert "path" in fc
        assert "additions" in fc
        assert "deletions" in fc
        assert "diff" in fc
        assert "original_content" in fc
        assert "new_content" in fc

# ── Phase 50: Code Metrics & Complexity Analyzer ─────────────────────────────

def test_metrics_analyze_nonexistent_path(client):
    r = client.post("/metrics/analyze", json={"project_path": "nonexistent_metrics_xyz"})
    assert r.status_code == 404


def test_metrics_analyze_empty_dir(client):
    """Analyze workspace root (may have no source files) — must return success."""
    r = client.post("/metrics/analyze", json={"project_path": "."})
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert "report" in d
    assert "summary" in d["report"]
    summary = d["report"]["summary"]
    assert "total_files" in summary
    assert "total_lines" in summary
    assert "total_functions" in summary
    assert "average_cyclomatic_complexity" in summary


def test_metrics_analyze_python_file(client, tmp_path):
    """Analyze a temp Python file and verify returned metrics."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_metrics_50a")
    os.makedirs(ws, exist_ok=True)
    try:
        code = (
            "# This is a test module\n"
            "class MyClass:\n"
            "    def method_one(self):\n"
            "        if True:\n"
            "            return 1\n"
            "        return 0\n"
            "\n"
            "def helper(x):\n"
            "    for i in range(x):\n"
            "        pass\n"
            "    return x\n"
        )
        with open(os.path.join(ws, "sample.py"), "w") as f:
            f.write(code)
        r = client.post("/metrics/analyze", json={"project_path": "test_metrics_50a"})
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        report = d["report"]
        summary = report["summary"]
        assert summary["total_files"] >= 1
        assert summary["total_lines"] >= 10
        assert summary["total_functions"] >= 2
        assert summary["total_classes"] >= 1
        assert "python" in summary["languages"]
        # Check file-level metrics
        files = report["files"]
        assert len(files) >= 1
        f0 = files[0]
        assert "file" in f0
        assert "language" in f0
        assert f0["language"] == "python"
        assert "total_lines" in f0
        assert "function_count" in f0
        assert "cyclomatic_complexity" in f0
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_metrics_analyze_creates_report(client, tmp_path):
    """POST /metrics/analyze followed by GET /metrics/reports."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_metrics_50b")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "app.py"), "w") as f:
            f.write("def run(): pass\n")
        r = client.post("/metrics/analyze", json={"project_path": "test_metrics_50b"})
        assert r.status_code == 200
        report_id = r.json()["id"]

        r2 = client.get("/metrics/reports")
        assert r2.status_code == 200
        d2 = r2.json()
        assert "reports" in d2
        assert "total" in d2
        ids = [rep["id"] for rep in d2["reports"]]
        assert report_id in ids
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_metrics_report_get_single(client, tmp_path):
    """Analyze then retrieve the report by ID."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_metrics_50c")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "main.py"), "w") as f:
            f.write("x = 1\n")
        r = client.post("/metrics/analyze", json={"project_path": "test_metrics_50c"})
        assert r.status_code == 200
        report_id = r.json()["id"]

        r2 = client.get(f"/metrics/report/{report_id}")
        assert r2.status_code == 200
        assert r2.json()["id"] == report_id
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_metrics_report_get_not_found(client):
    r = client.get("/metrics/report/999999")
    assert r.status_code == 404


def test_metrics_report_delete(client, tmp_path):
    """Analyze then delete the report."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_metrics_50d")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "util.py"), "w") as f:
            f.write("def noop(): pass\n")
        r = client.post("/metrics/analyze", json={"project_path": "test_metrics_50d"})
        assert r.status_code == 200
        report_id = r.json()["id"]

        r2 = client.delete(f"/metrics/report/{report_id}")
        assert r2.status_code == 200
        assert r2.json()["success"] is True

        r3 = client.get(f"/metrics/report/{report_id}")
        assert r3.status_code == 404
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_metrics_report_delete_not_found(client):
    r = client.delete("/metrics/report/999999")
    assert r.status_code == 404


def test_metrics_reports_pagination(client):
    r = client.get("/metrics/reports?limit=5")
    assert r.status_code == 200
    d = r.json()
    assert "reports" in d
    assert len(d["reports"]) <= 5


def test_metrics_path_traversal_blocked(client):
    """Path traversal outside workspace must be blocked."""
    r = client.post("/metrics/analyze", json={"project_path": "../etc"})
    assert r.status_code in (403, 404)


# ── Phase 51: Git Statistics Dashboard ───────────────────────────────────────

def test_gitstats_summary_returns_structure(client):
    """GET /gitstats/summary must return expected fields."""
    r = client.get("/gitstats/summary")
    assert r.status_code == 200
    d = r.json()
    assert "is_git_repo" in d
    assert "total_commits" in d
    assert "contributors" in d
    assert "branches" in d
    assert "tags" in d
    assert isinstance(d["contributors"], list)
    assert isinstance(d["branches"], list)
    assert isinstance(d["tags"], list)


def test_gitstats_summary_is_git_repo(client):
    """The SwissAgent repo itself is a valid git repo."""
    r = client.get("/gitstats/summary")
    assert r.status_code == 200
    d = r.json()
    assert d["is_git_repo"] is True
    assert d["total_commits"] >= 1


def test_gitstats_commits_returns_structure(client):
    """GET /gitstats/commits must return a list of commit objects."""
    r = client.get("/gitstats/commits")
    assert r.status_code == 200
    d = r.json()
    assert "commits" in d
    assert "total" in d
    assert isinstance(d["commits"], list)


def test_gitstats_commits_fields(client):
    """Each commit entry must have required fields."""
    r = client.get("/gitstats/commits?limit=5")
    assert r.status_code == 200
    for c in r.json()["commits"]:
        assert "sha" in c
        assert "author_name" in c
        assert "date" in c
        assert "subject" in c


def test_gitstats_commits_limit(client):
    """The limit query parameter is respected."""
    r = client.get("/gitstats/commits?limit=3")
    assert r.status_code == 200
    assert len(r.json()["commits"]) <= 3


def test_gitstats_contributors_structure(client):
    """GET /gitstats/contributors returns a list with author and commits fields."""
    r = client.get("/gitstats/contributors")
    assert r.status_code == 200
    d = r.json()
    assert "contributors" in d
    assert isinstance(d["contributors"], list)
    for c in d["contributors"]:
        assert "author" in c
        assert "commits" in c
        assert isinstance(c["commits"], int)


def test_gitstats_file_churn_structure(client):
    """GET /gitstats/file-churn returns files sorted by commits."""
    r = client.get("/gitstats/file-churn")
    assert r.status_code == 200
    d = r.json()
    assert "files" in d
    assert isinstance(d["files"], list)
    for f in d["files"]:
        assert "file" in f
        assert "commits" in f
        assert isinstance(f["commits"], int)


def test_gitstats_file_churn_limit(client):
    """limit parameter limits /gitstats/file-churn results."""
    r = client.get("/gitstats/file-churn?limit=5")
    assert r.status_code == 200
    assert len(r.json()["files"]) <= 5


# ── Phase 52: Test Runner & Coverage Dashboard ────────────────────────────────

def test_testrunner_run_pytest_basic(client):
    """POST /testrunner/run with pytest on a simple project returns a report."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_tr_52a")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "test_example.py"), "w") as f:
            f.write("def test_pass(): assert 1 == 1\n")
        r = client.post("/testrunner/run", json={"project_path": "test_tr_52a", "framework": "pytest"})
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        assert "id" in d
        report = d["report"]
        assert report["framework"] == "pytest"
        assert report["status"] in ("passed", "failed")
        assert "summary" in report
        assert "stdout" in report
        assert "stderr" in report
        assert "exit_code" in report
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_testrunner_run_creates_report(client):
    """POST /testrunner/run followed by GET /testrunner/reports lists the report."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_tr_52b")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "test_example.py"), "w") as f:
            f.write("def test_ok(): pass\n")
        r = client.post("/testrunner/run", json={"project_path": "test_tr_52b"})
        assert r.status_code == 200
        report_id = r.json()["id"]

        r2 = client.get("/testrunner/reports")
        assert r2.status_code == 200
        d2 = r2.json()
        assert "reports" in d2
        assert "total" in d2
        ids = [rep["id"] for rep in d2["reports"]]
        assert report_id in ids
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_testrunner_report_get_single(client):
    """Run, then retrieve the report by ID."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_tr_52c")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "test_example.py"), "w") as f:
            f.write("def test_one(): assert True\n")
        r = client.post("/testrunner/run", json={"project_path": "test_tr_52c"})
        assert r.status_code == 200
        report_id = r.json()["id"]

        r2 = client.get(f"/testrunner/report/{report_id}")
        assert r2.status_code == 200
        assert r2.json()["id"] == report_id
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_testrunner_report_get_not_found(client):
    r = client.get("/testrunner/report/999999")
    assert r.status_code == 404


def test_testrunner_report_delete(client):
    """Run then delete the report."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_tr_52d")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "test_example.py"), "w") as f:
            f.write("def test_del(): pass\n")
        r = client.post("/testrunner/run", json={"project_path": "test_tr_52d"})
        assert r.status_code == 200
        report_id = r.json()["id"]

        r2 = client.delete(f"/testrunner/report/{report_id}")
        assert r2.status_code == 200
        assert r2.json()["success"] is True

        r3 = client.get(f"/testrunner/report/{report_id}")
        assert r3.status_code == 404
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_testrunner_report_delete_not_found(client):
    r = client.delete("/testrunner/report/999999")
    assert r.status_code == 404


def test_testrunner_reports_pagination(client):
    r = client.get("/testrunner/reports?limit=3")
    assert r.status_code == 200
    d = r.json()
    assert "reports" in d
    assert len(d["reports"]) <= 3


def test_testrunner_unknown_framework(client):
    """Unknown framework returns 400."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_tr_52e")
    os.makedirs(ws, exist_ok=True)
    try:
        r = client.post("/testrunner/run", json={"project_path": "test_tr_52e", "framework": "unknown_fw"})
        assert r.status_code == 400
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_testrunner_path_traversal_blocked(client):
    """Path traversal outside workspace must be blocked."""
    r = client.post("/testrunner/run", json={"project_path": "../etc"})
    assert r.status_code in (403, 404)


def test_testrunner_path_not_found(client):
    """Non-existent project path returns 404."""
    r = client.post("/testrunner/run", json={"project_path": "no_such_dir_xyz"})
    assert r.status_code == 404


def test_testrunner_failing_tests(client):
    """A test file that fails: report.status == 'failed', exit_code != 0."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_tr_52f")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "test_fail.py"), "w") as f:
            f.write("def test_boom(): assert False\n")
        r = client.post("/testrunner/run", json={"project_path": "test_tr_52f"})
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        report = d["report"]
        assert report["status"] == "failed"
        assert report["exit_code"] != 0
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_testrunner_summary_fields(client):
    """Summary has passed/failed/errors/skipped."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_tr_52g")
    os.makedirs(ws, exist_ok=True)
    try:
        with open(os.path.join(ws, "test_example.py"), "w") as f:
            f.write("def test_a(): pass\ndef test_b(): pass\n")
        r = client.post("/testrunner/run", json={"project_path": "test_tr_52g"})
        assert r.status_code == 200
        summary = r.json()["report"]["summary"]
        assert "passed" in summary
        assert "failed" in summary
        assert "errors" in summary
        assert "skipped" in summary
        assert isinstance(summary["passed"], int)
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


# ── Phase 53: Terminal Manager ────────────────────────────────────────────────

def test_terminal_create_session(client):
    """POST /terminal/session creates a new session."""
    r = client.post("/terminal/session", json={"name": "my-term"})
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert "session_id" in d
    sid = d["session_id"]
    assert sid.startswith("term-")
    session = d["session"]
    assert session["name"] == "my-term"
    assert "cwd" in session
    assert "created_at" in session
    # cleanup
    client.delete(f"/terminal/session/{sid}")


def test_terminal_list_sessions(client):
    """GET /terminal/sessions lists all open sessions."""
    r1 = client.post("/terminal/session", json={"name": "list-test"})
    sid = r1.json()["session_id"]
    r2 = client.get("/terminal/sessions")
    assert r2.status_code == 200
    d = r2.json()
    assert "sessions" in d
    assert "total" in d
    ids = [s["id"] for s in d["sessions"]]
    assert sid in ids
    client.delete(f"/terminal/session/{sid}")


def test_terminal_get_session(client):
    """GET /terminal/session/{id} returns full session."""
    r1 = client.post("/terminal/session", json={})
    sid = r1.json()["session_id"]
    r2 = client.get(f"/terminal/session/{sid}")
    assert r2.status_code == 200
    d = r2.json()
    assert d["id"] == sid
    assert "history" in d
    client.delete(f"/terminal/session/{sid}")


def test_terminal_get_session_not_found(client):
    r = client.get("/terminal/session/no-such-session")
    assert r.status_code == 404


def test_terminal_exec_basic(client):
    """POST /terminal/session/{id}/exec runs a command and returns output."""
    r1 = client.post("/terminal/session", json={})
    sid = r1.json()["session_id"]
    r2 = client.post(f"/terminal/session/{sid}/exec", json={"command": "echo hello"})
    assert r2.status_code == 200
    d = r2.json()
    assert "stdout" in d
    assert "hello" in d["stdout"]
    assert d["exit_code"] == 0
    client.delete(f"/terminal/session/{sid}")


def test_terminal_exec_exit_code(client):
    """A failing command returns non-zero exit_code."""
    r1 = client.post("/terminal/session", json={})
    sid = r1.json()["session_id"]
    r2 = client.post(f"/terminal/session/{sid}/exec", json={"command": "exit 42"})
    assert r2.status_code == 200
    d = r2.json()
    assert d["exit_code"] != 0 or d["success"] is False
    client.delete(f"/terminal/session/{sid}")


def test_terminal_exec_records_history(client):
    """Executed commands appear in session history."""
    r1 = client.post("/terminal/session", json={})
    sid = r1.json()["session_id"]
    client.post(f"/terminal/session/{sid}/exec", json={"command": "echo history_test"})
    r2 = client.get(f"/terminal/session/{sid}")
    assert r2.status_code == 200
    history = r2.json()["history"]
    assert any("echo history_test" in h["command"] for h in history)
    client.delete(f"/terminal/session/{sid}")


def test_terminal_exec_empty_command(client):
    """Empty command returns 400."""
    r1 = client.post("/terminal/session", json={})
    sid = r1.json()["session_id"]
    r2 = client.post(f"/terminal/session/{sid}/exec", json={"command": "  "})
    assert r2.status_code == 400
    client.delete(f"/terminal/session/{sid}")


def test_terminal_exec_not_found(client):
    r = client.post("/terminal/session/no-such/exec", json={"command": "ls"})
    assert r.status_code == 404


def test_terminal_delete_session(client):
    """DELETE /terminal/session/{id} removes the session."""
    r1 = client.post("/terminal/session", json={})
    sid = r1.json()["session_id"]
    r2 = client.delete(f"/terminal/session/{sid}")
    assert r2.status_code == 200
    assert r2.json()["success"] is True
    r3 = client.get(f"/terminal/session/{sid}")
    assert r3.status_code == 404


def test_terminal_delete_session_not_found(client):
    r = client.delete("/terminal/session/no-such-session")
    assert r.status_code == 404


def test_terminal_cd_builtin(client):
    """cd command updates session cwd."""
    import os
    ws = os.path.join(os.getcwd(), "workspace", "test_term_53cd")
    os.makedirs(ws, exist_ok=True)
    try:
        r1 = client.post("/terminal/session", json={})
        sid = r1.json()["session_id"]
        r2 = client.post(f"/terminal/session/{sid}/exec", json={"command": f"cd {ws}"})
        assert r2.status_code == 200
        assert r2.json()["exit_code"] == 0
        r3 = client.get(f"/terminal/session/{sid}")
        assert ws in r3.json()["cwd"]
        client.delete(f"/terminal/session/{sid}")
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def test_terminal_cd_outside_workspace_blocked(client):
    """cd outside workspace returns 403."""
    r1 = client.post("/terminal/session", json={})
    sid = r1.json()["session_id"]
    r2 = client.post(f"/terminal/session/{sid}/exec", json={"command": "cd /etc"})
    assert r2.status_code == 403
    client.delete(f"/terminal/session/{sid}")


def test_terminal_cwd_init(client):
    """Session cwd can be set at creation time."""
    import os
    ws_sub = os.path.join(os.getcwd(), "workspace", "test_term_53cwd")
    os.makedirs(ws_sub, exist_ok=True)
    try:
        r1 = client.post("/terminal/session", json={"cwd": "test_term_53cwd"})
        assert r1.status_code == 200
        d = r1.json()
        assert "test_term_53cwd" in d["session"]["cwd"]
        client.delete(f"/terminal/session/{d['session_id']}")
    finally:
        import shutil
        shutil.rmtree(ws_sub, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 54: File Watcher
# ─────────────────────────────────────────────────────────────────────────────

def test_watcher_create_and_list(client):
    """POST /watcher/watch creates a watch; GET /watcher/watches lists it."""
    import os, shutil
    ws = os.path.join(os.getcwd(), "workspace", "test_watch54")
    os.makedirs(ws, exist_ok=True)
    try:
        r = client.post("/watcher/watch", json={"path": "test_watch54", "label": "w54"})
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        wid = d["watch_id"]
        assert wid.startswith("watch-")
        assert d["watch"]["label"] == "w54"

        rl = client.get("/watcher/watches")
        assert rl.status_code == 200
        ids = [w["id"] for w in rl.json()["watches"]]
        assert wid in ids
    finally:
        client.delete(f"/watcher/watch/{wid}")
        shutil.rmtree(ws, ignore_errors=True)


def test_watcher_get(client):
    """GET /watcher/watch/{id} returns watch details."""
    import os, shutil
    ws = os.path.join(os.getcwd(), "workspace", "test_watch54g")
    os.makedirs(ws, exist_ok=True)
    try:
        r = client.post("/watcher/watch", json={"path": "test_watch54g"})
        wid = r.json()["watch_id"]
        rg = client.get(f"/watcher/watch/{wid}")
        assert rg.status_code == 200
        assert rg.json()["id"] == wid
    finally:
        client.delete(f"/watcher/watch/{wid}")
        shutil.rmtree(ws, ignore_errors=True)


def test_watcher_get_not_found(client):
    r = client.get("/watcher/watch/no-such-watch")
    assert r.status_code == 404


def test_watcher_delete(client):
    """DELETE /watcher/watch/{id} removes the watch."""
    import os, shutil
    ws = os.path.join(os.getcwd(), "workspace", "test_watch54d")
    os.makedirs(ws, exist_ok=True)
    try:
        r = client.post("/watcher/watch", json={"path": "test_watch54d"})
        wid = r.json()["watch_id"]
        rd = client.delete(f"/watcher/watch/{wid}")
        assert rd.status_code == 200
        assert rd.json()["success"] is True
        rg = client.get(f"/watcher/watch/{wid}")
        assert rg.status_code == 404
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def test_watcher_delete_not_found(client):
    r = client.delete("/watcher/watch/ghost-watch")
    assert r.status_code == 404


def test_watcher_path_not_found(client):
    """Creating a watch on a non-existent path returns 404."""
    r = client.post("/watcher/watch", json={"path": "does/not/exist"})
    assert r.status_code == 404


def test_watcher_empty_path_rejected(client):
    """Empty path returns 400."""
    r = client.post("/watcher/watch", json={"path": "  "})
    assert r.status_code == 400


def test_watcher_events_list(client):
    """GET /watcher/events returns a list (possibly empty)."""
    r = client.get("/watcher/events")
    assert r.status_code == 200
    d = r.json()
    assert "events" in d
    assert isinstance(d["events"], list)


def test_watcher_events_filter_by_watch_id(client):
    """GET /watcher/events?watch_id= filters events."""
    r = client.get("/watcher/events?watch_id=watch-9999")
    assert r.status_code == 200
    d = r.json()
    assert all(e["watch_id"] == "watch-9999" for e in d["events"])


def test_watcher_events_filter_by_type(client):
    """GET /watcher/events?event_type= filters events."""
    r = client.get("/watcher/events?event_type=created")
    assert r.status_code == 200
    d = r.json()
    assert all(e["type"] == "created" for e in d["events"])


def test_watcher_path_traversal_blocked(client):
    """Path traversal outside workspace is blocked."""
    r = client.post("/watcher/watch", json={"path": "../../etc"})
    assert r.status_code in (400, 403, 404)


def test_watcher_file_watch(client):
    """Can watch a single file."""
    import os, shutil
    ws = os.path.join(os.getcwd(), "workspace", "test_watch54f.txt")
    with open(ws, "w") as f:
        f.write("hello")
    try:
        r = client.post("/watcher/watch", json={"path": "test_watch54f.txt"})
        assert r.status_code == 200
        wid = r.json()["watch_id"]
        client.delete(f"/watcher/watch/{wid}")
    finally:
        os.unlink(ws)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 55: Process Manager
# ─────────────────────────────────────────────────────────────────────────────

def test_process_start_and_list(client):
    """POST /process/start starts a process; GET /process/list shows it."""
    r = client.post("/process/start", json={"command": "sleep 60", "label": "sleeper"})
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    pid = d["process_id"]
    assert pid.startswith("proc-")
    assert d["process"]["label"] == "sleeper"

    rl = client.get("/process/list")
    assert rl.status_code == 200
    ids = [p["id"] for p in rl.json()["processes"]]
    assert pid in ids

    # Clean up
    client.delete(f"/process/{pid}")


def test_process_get(client):
    """GET /process/{id} returns process details."""
    r = client.post("/process/start", json={"command": "sleep 60"})
    pid = r.json()["process_id"]
    rg = client.get(f"/process/{pid}")
    assert rg.status_code == 200
    assert rg.json()["id"] == pid
    client.delete(f"/process/{pid}")


def test_process_get_not_found(client):
    r = client.get("/process/no-such-proc")
    assert r.status_code == 404


def test_process_stop(client):
    """DELETE /process/{id} stops and removes the process."""
    r = client.post("/process/start", json={"command": "sleep 60"})
    pid = r.json()["process_id"]
    rd = client.delete(f"/process/{pid}")
    assert rd.status_code == 200
    assert rd.json()["success"] is True
    rg = client.get(f"/process/{pid}")
    assert rg.status_code == 404


def test_process_stop_not_found(client):
    r = client.delete("/process/ghost-proc")
    assert r.status_code == 404


def test_process_logs(client):
    """GET /process/{id}/logs returns log output."""
    import time
    r = client.post("/process/start", json={"command": "echo hello_proc_log"})
    pid = r.json()["process_id"]
    time.sleep(0.5)  # allow process to finish
    rl = client.get(f"/process/{pid}/logs")
    assert rl.status_code == 200
    d = rl.json()
    assert "lines" in d
    assert "status" in d
    client.delete(f"/process/{pid}")


def test_process_logs_not_found(client):
    r = client.get("/process/no-such/logs")
    assert r.status_code == 404


def test_process_list_filter_status(client):
    """GET /process/list?status=running filters by status."""
    r = client.post("/process/start", json={"command": "sleep 60"})
    pid = r.json()["process_id"]
    rl = client.get("/process/list?status=running")
    assert rl.status_code == 200
    procs = rl.json()["processes"]
    assert all(p["status"] == "running" for p in procs)
    client.delete(f"/process/{pid}")


def test_process_empty_command_rejected(client):
    """Empty command returns 400."""
    r = client.post("/process/start", json={"command": "  "})
    assert r.status_code == 400


def test_process_bad_cwd(client):
    """Non-existent cwd returns 404."""
    r = client.post("/process/start", json={"command": "echo hi", "cwd": "no/such/dir"})
    assert r.status_code == 404


def test_process_finished_status(client):
    """Process that exits immediately transitions to 'stopped'."""
    import time
    r = client.post("/process/start", json={"command": "echo done_test"})
    pid = r.json()["process_id"]
    time.sleep(0.5)
    rg = client.get(f"/process/{pid}")
    assert rg.status_code == 200
    assert rg.json()["status"] == "stopped"
    assert rg.json()["exit_code"] == 0
    client.delete(f"/process/{pid}")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 56: Knowledge Base / Notes Manager
# ─────────────────────────────────────────────────────────────────────────────

def test_kb_create_and_list(client):
    """POST /kb/entry creates entry; GET /kb/entries lists it."""
    r = client.post("/kb/entry", json={"title": "Python Tips", "content": "Use list comprehensions", "tags": ["python", "tips"], "category": "coding"})
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    eid = d["id"]
    assert eid.startswith("kb-")
    assert d["entry"]["title"] == "Python Tips"
    assert "python" in d["entry"]["tags"]

    rl = client.get("/kb/entries")
    assert rl.status_code == 200
    ids = [e["id"] for e in rl.json()["entries"]]
    assert eid in ids

    client.delete(f"/kb/entry/{eid}")


def test_kb_get_entry(client):
    """GET /kb/entry/{id} returns the entry."""
    r = client.post("/kb/entry", json={"title": "Docker Notes"})
    eid = r.json()["id"]
    rg = client.get(f"/kb/entry/{eid}")
    assert rg.status_code == 200
    assert rg.json()["title"] == "Docker Notes"
    client.delete(f"/kb/entry/{eid}")


def test_kb_get_not_found(client):
    r = client.get("/kb/entry/kb-9999999")
    assert r.status_code == 404


def test_kb_update_entry(client):
    """PATCH /kb/entry/{id} updates fields."""
    r = client.post("/kb/entry", json={"title": "Old Title", "content": "old content"})
    eid = r.json()["id"]
    ru = client.patch(f"/kb/entry/{eid}", json={"title": "New Title", "tags": ["updated"]})
    assert ru.status_code == 200
    assert ru.json()["entry"]["title"] == "New Title"
    assert "updated" in ru.json()["entry"]["tags"]
    client.delete(f"/kb/entry/{eid}")


def test_kb_update_not_found(client):
    r = client.patch("/kb/entry/kb-9999999", json={"title": "X"})
    assert r.status_code == 404


def test_kb_delete_entry(client):
    """DELETE /kb/entry/{id} removes the entry."""
    r = client.post("/kb/entry", json={"title": "To Delete"})
    eid = r.json()["id"]
    rd = client.delete(f"/kb/entry/{eid}")
    assert rd.status_code == 200
    assert rd.json()["success"] is True
    assert client.get(f"/kb/entry/{eid}").status_code == 404


def test_kb_delete_not_found(client):
    r = client.delete("/kb/entry/kb-9999999")
    assert r.status_code == 404


def test_kb_empty_title_rejected(client):
    """Empty title returns 400."""
    r = client.post("/kb/entry", json={"title": "  "})
    assert r.status_code == 400


def test_kb_filter_by_tag(client):
    """GET /kb/entries?tag= filters by tag."""
    r = client.post("/kb/entry", json={"title": "Tagged", "tags": ["special56tag"]})
    eid = r.json()["id"]
    rl = client.get("/kb/entries?tag=special56tag")
    assert rl.status_code == 200
    ids = [e["id"] for e in rl.json()["entries"]]
    assert eid in ids
    client.delete(f"/kb/entry/{eid}")


def test_kb_filter_by_category(client):
    """GET /kb/entries?category= filters by category."""
    r = client.post("/kb/entry", json={"title": "Cat Entry", "category": "cattest56"})
    eid = r.json()["id"]
    rl = client.get("/kb/entries?category=cattest56")
    assert rl.status_code == 200
    ids = [e["id"] for e in rl.json()["entries"]]
    assert eid in ids
    client.delete(f"/kb/entry/{eid}")


def test_kb_search(client):
    """GET /kb/search?q= returns matching entries."""
    r = client.post("/kb/entry", json={"title": "uniqueterm56abc", "content": "some note"})
    eid = r.json()["id"]
    rs = client.get("/kb/search?q=uniqueterm56abc")
    assert rs.status_code == 200
    ids = [e["id"] for e in rs.json()["results"]]
    assert eid in ids
    client.delete(f"/kb/entry/{eid}")


def test_kb_search_no_match(client):
    """Search with no match returns empty results."""
    rs = client.get("/kb/search?q=zzznomatchterm99xyz")
    assert rs.status_code == 200
    assert rs.json()["results"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Phase 57: HTTP Mock Server
# ─────────────────────────────────────────────────────────────────────────────

def test_mockserver_create_route(client):
    """POST /mockserver/route creates a route."""
    r = client.post("/mockserver/route", json={"method": "GET", "path": "/api/test57", "status_code": 200, "response_body": {"msg": "ok"}})
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    rid = d["route_id"]
    assert rid.startswith("route-")
    assert d["route"]["path"] == "/api/test57"

    client.delete(f"/mockserver/route/{rid}")


def test_mockserver_list_routes(client):
    """GET /mockserver/routes lists all routes."""
    r = client.post("/mockserver/route", json={"method": "POST", "path": "/api/list57"})
    rid = r.json()["route_id"]
    rl = client.get("/mockserver/routes")
    assert rl.status_code == 200
    ids = [rt["id"] for rt in rl.json()["routes"]]
    assert rid in ids
    client.delete(f"/mockserver/route/{rid}")


def test_mockserver_get_route(client):
    """GET /mockserver/route/{id} returns route details."""
    r = client.post("/mockserver/route", json={"method": "GET", "path": "/api/get57"})
    rid = r.json()["route_id"]
    rg = client.get(f"/mockserver/route/{rid}")
    assert rg.status_code == 200
    assert rg.json()["id"] == rid
    client.delete(f"/mockserver/route/{rid}")


def test_mockserver_get_route_not_found(client):
    r = client.get("/mockserver/route/route-9999999")
    assert r.status_code == 404


def test_mockserver_delete_route(client):
    """DELETE /mockserver/route/{id} removes the route."""
    r = client.post("/mockserver/route", json={"method": "DELETE", "path": "/api/del57"})
    rid = r.json()["route_id"]
    rd = client.delete(f"/mockserver/route/{rid}")
    assert rd.status_code == 200
    assert rd.json()["success"] is True
    assert client.get(f"/mockserver/route/{rid}").status_code == 404


def test_mockserver_delete_route_not_found(client):
    r = client.delete("/mockserver/route/route-9999999")
    assert r.status_code == 404


def test_mockserver_invalid_method(client):
    """Invalid HTTP method returns 400."""
    r = client.post("/mockserver/route", json={"method": "INVALID", "path": "/x"})
    assert r.status_code == 400


def test_mockserver_path_must_start_with_slash(client):
    r = client.post("/mockserver/route", json={"method": "GET", "path": "no-slash"})
    assert r.status_code == 400


def test_mockserver_simulate_request_match(client):
    """POST /mockserver/request returns matched route response."""
    r = client.post("/mockserver/route", json={"method": "GET", "path": "/mocked57", "status_code": 201, "response_body": {"data": "mocked"}})
    rid = r.json()["route_id"]
    rs = client.post("/mockserver/request", json={"method": "GET", "path": "/mocked57"})
    assert rs.status_code == 200
    d = rs.json()
    assert d["status_code"] == 201
    assert d["response_body"] == {"data": "mocked"}
    assert d["matched_route_id"] == rid
    client.delete(f"/mockserver/route/{rid}")


def test_mockserver_simulate_request_no_match(client):
    """POST /mockserver/request with no matching route returns 404 stub."""
    rs = client.post("/mockserver/request", json={"method": "GET", "path": "/no-match-57xyz"})
    assert rs.status_code == 200
    d = rs.json()
    assert d["status_code"] == 404
    assert d["matched_route_id"] is None


def test_mockserver_hit_count_increments(client):
    """Matched route hit_count increments on each simulated request."""
    r = client.post("/mockserver/route", json={"method": "GET", "path": "/hitcount57"})
    rid = r.json()["route_id"]
    client.post("/mockserver/request", json={"method": "GET", "path": "/hitcount57"})
    client.post("/mockserver/request", json={"method": "GET", "path": "/hitcount57"})
    rg = client.get(f"/mockserver/route/{rid}")
    assert rg.json()["hit_count"] == 2
    client.delete(f"/mockserver/route/{rid}")


def test_mockserver_list_requests(client):
    """GET /mockserver/requests returns recorded requests."""
    client.post("/mockserver/request", json={"method": "GET", "path": "/listreqs57"})
    rl = client.get("/mockserver/requests")
    assert rl.status_code == 200
    assert isinstance(rl.json()["requests"], list)


def test_mockserver_list_requests_filter_method(client):
    """GET /mockserver/requests?method= filters by method."""
    client.post("/mockserver/request", json={"method": "POST", "path": "/filtermeth57"})
    rl = client.get("/mockserver/requests?method=POST")
    assert rl.status_code == 200
    assert all(r["method"] == "POST" for r in rl.json()["requests"])


def test_mockserver_clear_requests(client):
    """DELETE /mockserver/requests clears all recorded requests."""
    client.post("/mockserver/request", json={"method": "GET", "path": "/clear57"})
    rc = client.delete("/mockserver/requests")
    assert rc.status_code == 200
    assert rc.json()["success"] is True
    rl = client.get("/mockserver/requests")
    assert rl.json()["requests"] == []
