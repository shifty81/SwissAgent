"""Module tests."""
from __future__ import annotations
from pathlib import Path
import pytest


def test_filesystem_write_read(tmp_path):
    from modules.filesystem.src.filesystem import write_file, read_file
    p = str(tmp_path / "test.txt")
    write_file(p, "hello world")
    assert read_file(p) == "hello world"


def test_filesystem_list_directory(tmp_path):
    from modules.filesystem.src.filesystem import write_file, list_directory
    write_file(str(tmp_path / "a.txt"), "a")
    write_file(str(tmp_path / "b.txt"), "b")
    entries = list_directory(str(tmp_path))
    assert any("a.txt" in e for e in entries)
    assert any("b.txt" in e for e in entries)


def test_filesystem_copy_delete(tmp_path):
    from modules.filesystem.src.filesystem import write_file, copy_file, delete_file
    src, dst = str(tmp_path / "src.txt"), str(tmp_path / "dst.txt")
    write_file(src, "content")
    copy_file(src, dst)
    assert Path(dst).exists()
    delete_file(src)
    assert not Path(src).exists()


def test_zip_pack_extract(tmp_path):
    from modules.zip.src.zip_tools import zip_pack, zip_extract
    src = tmp_path / "mydir"
    src.mkdir()
    (src / "hello.txt").write_text("hi")
    archive = str(tmp_path / "out.zip")
    dst = str(tmp_path / "extracted")
    zip_pack(str(src), archive)
    zip_extract(archive, dst)
    # shutil.make_archive packs contents of src, not src itself
    assert (Path(dst) / "hello.txt").exists()


def test_image_info(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    from modules.image.src.image_tools import image_info
    img_path = str(tmp_path / "test.png")
    Image.new("RGB", (100, 100), color=(255, 0, 0)).save(img_path)
    info = image_info(img_path)
    assert info["size"] == [100, 100]


def test_cache_set_get(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from modules.cache.src import cache_manager
    cache_manager._CACHE_DIR = tmp_path / "cache"
    cache_manager.cache_set("mykey", "myvalue")
    result = cache_manager.cache_get("mykey")
    assert result["hit"] is True
    assert result["value"] == "myvalue"


def test_memory_store_recall(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from modules.memory.src.memory import memory_store, memory_recall
    memory_store("greeting", "hello", namespace="test")
    result = memory_recall("greeting", namespace="test")
    assert result["found"] is True and result["value"] == "hello"


def test_security_hash_verify(tmp_path):
    from modules.security.src.security import hash_file, verify_hash
    p = tmp_path / "data.bin"
    p.write_bytes(b"abc123")
    result = hash_file(str(p))
    assert len(result["hash"]) == 64
    assert verify_hash(str(p), result["hash"])["match"] is True


# ---------------------------------------------------------------------------
# Build module
# ---------------------------------------------------------------------------

def test_build_cmake_missing_dir(tmp_path):
    from modules.build.src.build_tools import build_cmake
    result = build_cmake(str(tmp_path / "nonexistent"), str(tmp_path / "build"))
    # Should return a result dict (may fail if cmake not installed)
    assert isinstance(result, dict)


def test_build_custom(tmp_path):
    from modules.build.src.build_tools import build_custom
    result = build_custom(str(tmp_path), "python --version")
    assert isinstance(result, dict)
    assert "returncode" in result


# ---------------------------------------------------------------------------
# Script module — extended language runners
# ---------------------------------------------------------------------------

def test_script_eval_python():
    from modules.script.src.script_runner import eval_python
    result = eval_python("x = 1 + 2\nprint(x)")
    assert result["returncode"] == 0
    assert "3" in result["stdout"]


def test_script_run_python_file(tmp_path):
    from modules.script.src.script_runner import run_python
    script = tmp_path / "hello.py"
    script.write_text("print('swissagent')")
    result = run_python(str(script))
    assert result["returncode"] == 0
    assert "swissagent" in result["stdout"]


def test_script_run_nonexistent():
    from modules.script.src.script_runner import run_go
    result = run_go("/nonexistent/main.go")
    assert "returncode" in result


# ---------------------------------------------------------------------------
# Stage manager
# ---------------------------------------------------------------------------

def test_stage_manager_progression(tmp_path):
    from stage_manager.stage_manager import StageManager
    sm = StageManager(state_file=str(tmp_path / "stage.json"))
    assert sm.current_stage == 0
    assert not sm.is_complete()
    goal = sm.get_stage_goal()
    assert "Stage 0" in goal

    sm.mark_stage_complete()
    assert sm.current_stage == 1

    # Advance through all stages
    while not sm.is_complete():
        sm.mark_stage_complete()
    assert sm.is_complete()


def test_stage_manager_persistence(tmp_path):
    from stage_manager.stage_manager import StageManager
    state_file = str(tmp_path / "stage.json")
    sm1 = StageManager(state_file=state_file)
    sm1.mark_stage_complete()
    assert sm1.current_stage == 1

    sm2 = StageManager(state_file=state_file)
    assert sm2.current_stage == 1


# ---------------------------------------------------------------------------
# Dev mode
# ---------------------------------------------------------------------------

def test_dev_mode_dry_run(tmp_path):
    from dev_mode.self_upgrade import DevMode
    dm = DevMode(staging_dir=str(tmp_path / "staging"))
    result = dm.upgrade_file("tools/build_runner.py", "# new content", dry_run=True)
    assert result["dry_run"] is True
    staged = dm.list_staged()
    assert len(staged) >= 1


def test_dev_mode_status(tmp_path):
    from dev_mode.self_upgrade import DevMode
    dm = DevMode(staging_dir=str(tmp_path / "staging"))
    status = dm.status()
    assert "staging_dir" in status
    assert "staged_count" in status


# ---------------------------------------------------------------------------
# Tools: feedback_parser
# ---------------------------------------------------------------------------

def test_feedback_parser_no_errors():
    from tools.feedback_parser import FeedbackParser
    parser = FeedbackParser()
    result = parser.parse("Build successful.")
    assert len(result.errors) == 0
    assert not result.has_failures


def test_feedback_parser_python_import():
    from tools.feedback_parser import FeedbackParser
    parser = FeedbackParser()
    result = parser.parse("ModuleNotFoundError: No module named 'numpy'")
    assert len(result.errors) == 1
    assert result.errors[0].kind == "missing_import"
    assert "pip install" in result.errors[0].suggestion


def test_feedback_parser_build_failed():
    from tools.feedback_parser import FeedbackParser
    parser = FeedbackParser()
    result = parser.parse("BUILD FAILED\nerror: undefined reference to `main'")
    assert result.has_failures


# ---------------------------------------------------------------------------
# Tools: build_runner
# ---------------------------------------------------------------------------

def test_build_runner_no_src(tmp_path):
    from tools.build_runner import BuildRunner
    runner = BuildRunner()
    output = runner.run(str(tmp_path))
    assert "No src/ directory" in output


def test_build_runner_python(tmp_path):
    from tools.build_runner import BuildRunner
    src = tmp_path / "src" / "python"
    src.mkdir(parents=True)
    (src / "hello.py").write_text("print('hello from build runner')")
    runner = BuildRunner()
    output = runner.run(str(tmp_path))
    assert "hello from build runner" in output


def test_build_runner_hot_reload():
    from tools.build_runner import BuildRunner
    runner = BuildRunner()
    # Hot-reload a stdlib module — should succeed
    result = runner.hot_reload("json")
    assert result.get("success") is True


# ---------------------------------------------------------------------------
# Tools: media_pipeline
# ---------------------------------------------------------------------------

def test_media_pipeline_2d_image(tmp_path):
    from tools.media_pipeline import generate_2d_image
    result = generate_2d_image("a blue background", "test.png", workspace=str(tmp_path))
    assert Path(result["generated"]).exists()


def test_media_pipeline_texture(tmp_path):
    pytest.importorskip("PIL")
    from tools.media_pipeline import generate_texture
    result = generate_texture("mytex.png", workspace=str(tmp_path))
    assert Path(result["generated"]).exists()


def test_media_pipeline_manifest(tmp_path):
    from tools.media_pipeline import generate_2d_image, generate_asset_manifest
    generate_2d_image("something", "a.png", workspace=str(tmp_path))
    result = generate_asset_manifest(workspace=str(tmp_path))
    assert result["count"] >= 1


# ---------------------------------------------------------------------------
# Animation module
# ---------------------------------------------------------------------------

def test_animation_create_template(tmp_path):
    from modules.animation.src.animation import anim_create_template, anim_import
    path = str(tmp_path / "anim.json")
    create_result = anim_create_template(path, bone_names=["root", "spine"], frame_count=10)
    assert create_result["frames"] == 10
    import_result = anim_import(path)
    assert import_result["frames"] == 10


def test_animation_bake(tmp_path):
    from modules.animation.src.animation import anim_create_template, anim_bake
    path = str(tmp_path / "anim.json")
    anim_create_template(path, bone_names=["root"], frame_count=60)
    result = anim_bake(path, fps=30)
    assert result.get("fps") == 30


# ---------------------------------------------------------------------------
# UI module
# ---------------------------------------------------------------------------

def test_ui_generate_button():
    from modules.ui.src.ui import ui_generate_component
    result = ui_generate_component("button", "play_btn", framework="imgui")
    assert "play_btn" in result["code"]
    assert result["framework"] == "imgui"


def test_ui_list_components():
    from modules.ui.src.ui import ui_list_components
    result = ui_list_components()
    assert "imgui" in result
    assert "html" in result


def test_ui_generate_layout(tmp_path):
    from modules.ui.src.ui import ui_generate_layout
    comps = [{"type": "button", "name": "ok_btn"}, {"type": "window", "name": "main_win"}]
    result = ui_generate_layout(comps, str(tmp_path / "layout.cpp"))
    assert Path(result["layout"]).exists()
    assert result["component_count"] == 2


# ---------------------------------------------------------------------------
# Shader module
# ---------------------------------------------------------------------------

def test_shader_generate_glsl_template(tmp_path):
    from modules.shader.src.shader import generate_glsl_template
    vert = str(tmp_path / "shader.vert")
    frag = str(tmp_path / "shader.frag")
    result = generate_glsl_template(vert, frag, color=(1.0, 0.0, 0.0))
    assert Path(vert).exists()
    assert Path(frag).exists()
    assert "#version" in Path(vert).read_text()


def test_shader_generate_hlsl_template(tmp_path):
    from modules.shader.src.shader import generate_hlsl_template
    dst = str(tmp_path / "shader.hlsl")
    result = generate_hlsl_template(dst)
    assert Path(dst).exists()
    assert "float4" in Path(dst).read_text()


# ---------------------------------------------------------------------------
# Tile module
# ---------------------------------------------------------------------------

def test_tile_create_map():
    from modules.tile.src.tile import tile_create_map
    result = tile_create_map(10, 8, default_tile=0)
    tilemap = result["tilemap"]
    assert tilemap["width"] == 10
    assert tilemap["height"] == 8
    assert len(tilemap["layers"][0]["data"]) == 80


def test_tile_export_import(tmp_path):
    from modules.tile.src.tile import tile_create_map, tile_export
    import json
    result = tile_create_map(4, 4)
    dst = str(tmp_path / "map.json")
    tile_export(result["tilemap"], dst)
    loaded = json.loads(Path(dst).read_text())
    assert loaded["width"] == 4


# ---------------------------------------------------------------------------
# Stable Diffusion stub
# ---------------------------------------------------------------------------

def test_stable_diffusion_stub(tmp_path):
    from stable_diffusion.stable_diffusion_interface import StableDiffusionInterface
    sd = StableDiffusionInterface()  # no model path → stub mode
    out = str(tmp_path / "img.png")
    result = sd.generate("a red square", out)
    assert Path(out).exists()
    assert result["engine"] in {"pillow_stub", "placeholder"}


# ---------------------------------------------------------------------------
# Audio pipeline
# ---------------------------------------------------------------------------

def test_audio_pipeline_placeholder_wav(tmp_path):
    from audio_pipeline.tts_sfx import AudioPipeline
    pipeline = AudioPipeline()
    out = str(tmp_path / "voice.wav")
    result = pipeline.generate_tts("hello world", out)
    assert Path(out).exists()


def test_audio_pipeline_sfx_tone(tmp_path):
    from audio_pipeline.tts_sfx import AudioPipeline
    pipeline = AudioPipeline()
    out = str(tmp_path / "sfx.wav")
    result = pipeline.generate_sfx("click", out, frequency=880.0, duration=0.1)
    assert Path(out).exists()
    assert result["engine"] in {"sox", "tone_stub", "placeholder"}


def test_audio_pipeline_music_placeholder(tmp_path):
    from audio_pipeline.tts_sfx import AudioPipeline
    pipeline = AudioPipeline()
    out = str(tmp_path / "music.wav")
    result = pipeline.generate_music_placeholder(out, duration=0.5)
    assert Path(out).exists()



# ---------------------------------------------------------------------------
# Blender module (no Blender installed — expect graceful "not found" errors)
# ---------------------------------------------------------------------------

def test_blender_open_no_blender(tmp_path):
    from modules.blender.src.blender import blender_open
    result = blender_open(path=str(tmp_path / "nonexistent.blend"))
    # Either "not found" error (no blender exe) or "file not found" error
    assert result.get("status") == "error"
    assert "error" in result


def test_blender_render_no_blender(tmp_path):
    from modules.blender.src.blender import blender_render
    result = blender_render(blend_file=str(tmp_path / "scene.blend"))
    assert result.get("status") == "error"


def test_blender_export_unsupported_format(tmp_path):
    from modules.blender.src.blender import blender_export
    blend = tmp_path / "scene.blend"
    blend.write_bytes(b"")
    result = blender_export(blend_file=str(blend), format="UNKNOWN", dst=str(tmp_path / "out.xyz"))
    # Blender not found OR unsupported format — both are errors
    assert result.get("status") == "error"


def test_blender_script_no_blender(tmp_path):
    from modules.blender.src.blender import blender_script
    blend = tmp_path / "scene.blend"
    blend.write_bytes(b"")
    result = blender_script(blend_file=str(blend), script="print('hello')")
    assert result.get("status") == "error"


def test_blender_bake_no_blender(tmp_path):
    from modules.blender.src.blender import blender_bake
    blend = tmp_path / "scene.blend"
    blend.write_bytes(b"")
    result = blender_bake(blend_file=str(blend), output_dir=str(tmp_path / "bake"))
    assert result.get("status") == "error"


# ---------------------------------------------------------------------------
# Installer module
# ---------------------------------------------------------------------------

def test_installer_install_deps_no_manifest(tmp_path):
    from modules.installer.src.installer import install_deps
    result = install_deps(path=str(tmp_path))
    assert result["status"] == "nothing_to_install"


def test_installer_install_deps_requirements(tmp_path):
    from modules.installer.src.installer import install_deps
    (tmp_path / "requirements.txt").write_text("# empty requirements\n")
    result = install_deps(path=str(tmp_path))
    # pip run with empty requirements — should succeed
    assert result["status"] in ("ok", "partial")
    assert "pip" in result.get("installed", []) or any(r["manager"] == "pip" for r in result.get("results", []))


def test_installer_create_installer_zip(tmp_path):
    from modules.installer.src.installer import create_installer
    src = tmp_path / "project"
    src.mkdir()
    (src / "main.py").write_text("print('hello')")
    out = str(tmp_path / "release.zip")
    result = create_installer(path=str(src), output=out, platform="zip")
    assert result["status"] == "ok"
    assert Path(result["installer"]).exists()
    assert result["size_bytes"] > 0
    assert "sha256" in result


def test_installer_create_installer_tar(tmp_path):
    from modules.installer.src.installer import create_installer
    src = tmp_path / "project"
    src.mkdir()
    (src / "main.py").write_text("# code")
    out = str(tmp_path / "release.tar.gz")
    result = create_installer(path=str(src), output=out, platform="tar")
    assert result["status"] == "ok"
    assert Path(result["installer"]).exists()


def test_installer_create_installer_bad_platform(tmp_path):
    from modules.installer.src.installer import create_installer
    src = tmp_path / "project"
    src.mkdir()
    result = create_installer(path=str(src), output=str(tmp_path / "out"), platform="nsis")
    assert result["status"] == "error"


def test_installer_verify_install_empty(tmp_path):
    from modules.installer.src.installer import verify_install
    result = verify_install(path=str(tmp_path))
    assert result["status"] in ("ok", "incomplete", "nothing_to_install")


def test_installer_verify_install_bad_path():
    from modules.installer.src.installer import verify_install
    result = verify_install(path="/nonexistent/path")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Job module
# ---------------------------------------------------------------------------

def test_job_submit_and_status():
    from modules.job.src.job import job_submit, job_status
    result = job_submit(task="echo hello")
    assert result["status"] == "submitted"
    jid = result["job_id"]
    status = job_status(job_id=jid)
    assert status["job_id"] == jid
    assert status["status"] in ("queued", "running", "done", "failed")


def test_job_list():
    from modules.job.src.job import job_submit, job_list
    job_submit(task="echo list_test")
    result = job_list()
    assert "jobs" in result
    assert result["count"] >= 1


def test_job_list_filtered():
    from modules.job.src.job import job_list
    result = job_list(status="nonexistent_status")
    assert result["count"] == 0


def test_job_result_unknown():
    from modules.job.src.job import job_result
    result = job_result(job_id="doesnotexist")
    assert result["status"] == "error"


def test_job_cancel_unknown():
    from modules.job.src.job import job_cancel
    result = job_cancel(job_id="doesnotexist")
    assert result["status"] == "error"


def test_job_submit_and_wait(tmp_path):
    import time
    from modules.job.src.job import job_submit, job_status, job_result
    result = job_submit(task="python -c \"print('job_done')\"")
    jid = result["job_id"]
    # Poll briefly
    for _ in range(20):
        s = job_status(job_id=jid)
        if s["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    final = job_result(job_id=jid)
    assert final["status"] in ("done", "failed")


# ---------------------------------------------------------------------------
# Debug module
# ---------------------------------------------------------------------------

def test_debug_attach_current_process():
    import os
    from modules.debug.src.debug import debug_attach
    result = debug_attach(pid=os.getpid())
    assert result["status"] == "ok"
    assert result["info"]["pid"] == os.getpid()


def test_debug_attach_nonexistent():
    from modules.debug.src.debug import debug_attach
    result = debug_attach(pid=9999999)
    assert result["status"] == "error"


def test_debug_breakpoint_valid(tmp_path):
    from modules.debug.src.debug import debug_breakpoint
    src = tmp_path / "script.py"
    src.write_text("x = 1\ny = 2\n")
    result = debug_breakpoint(file=str(src), line=1)
    assert result["status"] == "ok"
    assert result["line"] == 1
    assert "x = 1" in result["code"]


def test_debug_breakpoint_out_of_range(tmp_path):
    from modules.debug.src.debug import debug_breakpoint
    src = tmp_path / "script.py"
    src.write_text("x = 1\n")
    result = debug_breakpoint(file=str(src), line=999)
    assert result["status"] == "error"


def test_debug_trace_current_process():
    import os
    from modules.debug.src.debug import debug_trace
    result = debug_trace(pid=os.getpid())
    assert result["status"] == "ok"
    assert "frames" in result


def test_debug_memory_current_process():
    import os
    from modules.debug.src.debug import debug_memory
    result = debug_memory(pid=os.getpid())
    assert result["status"] == "ok"
    assert "memory" in result


# ---------------------------------------------------------------------------
# Profile module
# ---------------------------------------------------------------------------

def test_profile_cpu_expression():
    from modules.profile.src.profile import profile_cpu
    result = profile_cpu(command="x = sum(range(100))")
    assert result["status"] == "ok"
    assert "top_functions" in result


def test_profile_cpu_file(tmp_path):
    from modules.profile.src.profile import profile_cpu
    script = tmp_path / "compute.py"
    script.write_text("result = [i*i for i in range(1000)]\n")
    result = profile_cpu(command=str(script))
    assert result["status"] == "ok"


def test_profile_cpu_output(tmp_path):
    from modules.profile.src.profile import profile_cpu
    out = str(tmp_path / "cpu_profile.json")
    result = profile_cpu(command="pass", output=out)
    assert result["status"] == "ok"
    assert Path(out).exists()


def test_profile_memory_expression():
    from modules.profile.src.profile import profile_memory
    result = profile_memory(command="data = list(range(1000))")
    assert result["status"] == "ok"
    assert "top_allocations" in result


def test_profile_memory_output(tmp_path):
    from modules.profile.src.profile import profile_memory
    out = str(tmp_path / "mem_profile.json")
    result = profile_memory(command="x = 1", output=out)
    assert result["status"] == "ok"
    assert Path(out).exists()


def test_profile_report_json(tmp_path):
    from modules.profile.src.profile import profile_cpu, profile_report
    out_json = str(tmp_path / "cpu.json")
    profile_cpu(command="pass", output=out_json)
    result = profile_report(profile_data=out_json)
    assert result["status"] == "ok"
    assert "report" in result


def test_profile_report_missing():
    from modules.profile.src.profile import profile_report
    result = profile_report(profile_data="/nonexistent/profile.json")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Editor module
# ---------------------------------------------------------------------------

def test_editor_format_json(tmp_path):
    from modules.editor.src.editor import editor_format
    f = tmp_path / "data.json"
    f.write_text('{"b":2,"a":1}')
    result = editor_format(path=str(f))
    assert result["status"] == "ok"
    import json
    loaded = json.loads(f.read_text())
    assert loaded["a"] == 1


def test_editor_format_missing_file():
    from modules.editor.src.editor import editor_format
    result = editor_format(path="/nonexistent/file.py")
    assert result["status"] == "error"


def test_editor_lint_missing_file():
    from modules.editor.src.editor import editor_lint
    result = editor_lint(path="/nonexistent/file.py")
    assert result["status"] == "error"


def test_editor_search_pattern(tmp_path):
    from modules.editor.src.editor import editor_search
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "b.py").write_text("class Bar:\n    pass\n")
    result = editor_search(pattern="def ", directory=str(tmp_path))
    assert result["status"] == "ok"
    assert result["count"] >= 1
    assert any("foo" in m["text"] for m in result["matches"])


def test_editor_search_no_matches(tmp_path):
    from modules.editor.src.editor import editor_search
    (tmp_path / "x.py").write_text("pass\n")
    result = editor_search(pattern="UNLIKELY_PATTERN_XYZ", directory=str(tmp_path))
    assert result["status"] == "ok"
    assert result["count"] == 0


def test_editor_search_bad_dir():
    from modules.editor.src.editor import editor_search
    result = editor_search(pattern="foo", directory="/nonexistent")
    assert result["status"] == "error"


def test_editor_replace(tmp_path):
    from modules.editor.src.editor import editor_replace
    f = tmp_path / "code.py"
    f.write_text("old_name = 1\nold_name += 2\n")
    result = editor_replace(pattern="old_name", replacement="new_name", directory=str(tmp_path))
    assert result["status"] == "ok"
    assert result["total_replacements"] == 2
    assert "new_name" in f.read_text()


def test_editor_replace_no_matches(tmp_path):
    from modules.editor.src.editor import editor_replace
    f = tmp_path / "code.py"
    f.write_text("x = 1\n")
    result = editor_replace(pattern="NOTFOUND", replacement="x", directory=str(tmp_path))
    assert result["status"] == "ok"
    assert result["total_replacements"] == 0


# ---------------------------------------------------------------------------
# Server module
# ---------------------------------------------------------------------------

def test_server_list_empty():
    # New process may have servers from other tests; at minimum the call succeeds
    from modules.server.src.server import server_list
    result = server_list()
    assert "servers" in result
    assert "count" in result


def test_server_start_stop(tmp_path):
    from modules.server.src.server import server_start, server_stop, server_status
    result = server_start(path=str(tmp_path), port=18080)
    assert result["status"] == "ok"
    sid = result["server_id"]
    status = server_status(server_id=sid)
    assert status["status"] == "running"
    stop = server_stop(server_id=sid)
    assert stop["status"] == "stopped"


def test_server_status_missing():
    from modules.server.src.server import server_status
    result = server_status(server_id="doesnotexist")
    assert result["status"] == "error"


def test_server_logs_missing():
    from modules.server.src.server import server_logs
    result = server_logs(server_id="doesnotexist")
    assert result["status"] == "error"


def test_server_stop_missing():
    from modules.server.src.server import server_stop
    result = server_stop(server_id="doesnotexist")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Asset module
# ---------------------------------------------------------------------------

def test_asset_import_export(tmp_path):
    from modules.asset.src.asset import asset_import, asset_export, asset_list, asset_delete
    src = tmp_path / "tex.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)  # fake PNG header
    result = asset_import(path=str(src), type="texture", name="test_tex")
    assert result["status"] == "ok"
    aid = result["asset_id"]

    lst = asset_list()
    assert any(a["id"] == aid for a in lst["assets"])

    dst = str(tmp_path / "exported_tex.png")
    exp = asset_export(asset_id=aid, dst=dst)
    assert exp["status"] == "ok"
    assert Path(dst).exists()

    # Delete
    del_result = asset_delete(asset_id=aid)
    assert del_result["status"] == "ok"

    # Confirm gone
    lst2 = asset_list()
    assert all(a["id"] != aid for a in lst2["assets"])


def test_asset_metadata(tmp_path):
    from modules.asset.src.asset import asset_import, asset_metadata
    src = tmp_path / "sound.wav"
    src.write_bytes(b"RIFF" + b"\x00" * 8)
    result = asset_import(path=str(src), type="audio")
    aid = result["asset_id"]
    meta = asset_metadata(asset_id=aid)
    assert meta["status"] == "ok"
    assert meta["asset"]["type"] == "audio"


def test_asset_missing():
    from modules.asset.src.asset import asset_metadata
    result = asset_metadata(asset_id="nonexistent_id")
    assert result["status"] == "error"


def test_asset_import_missing_file():
    from modules.asset.src.asset import asset_import
    result = asset_import(path="/nonexistent/file.png", type="texture")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Doc module
# ---------------------------------------------------------------------------

def test_doc_generate_markdown(tmp_path):
    from modules.doc.src.doc import doc_generate
    src = tmp_path / "mymodule.py"
    src.write_text('"""My module docstring."""\n\ndef hello():\n    """Say hello."""\n    pass\n')
    out = str(tmp_path / "docs.md")
    result = doc_generate(src=str(tmp_path), output=out)
    assert result["status"] == "ok"
    assert Path(out).exists()
    content = Path(out).read_text()
    assert "hello" in content


def test_doc_generate_json(tmp_path):
    from modules.doc.src.doc import doc_generate
    src = tmp_path / "mod.py"
    src.write_text('"""Mod."""\ndef func():\n    """Func doc."""\n    pass\n')
    out = str(tmp_path / "docs.json")
    result = doc_generate(src=str(tmp_path), output=out, format="json")
    assert result["status"] == "ok"
    import json
    data = json.loads(Path(out).read_text())
    assert "modules" in data


def test_doc_generate_html(tmp_path):
    from modules.doc.src.doc import doc_generate
    src = tmp_path / "mod.py"
    src.write_text('def foo():\n    """Foo doc."""\n    pass\n')
    out = str(tmp_path / "docs.html")
    result = doc_generate(src=str(tmp_path), output=out, format="html")
    assert result["status"] == "ok"
    assert "<html>" in Path(out).read_text()


def test_doc_generate_missing_src(tmp_path):
    from modules.doc.src.doc import doc_generate
    result = doc_generate(src="/nonexistent/src", output=str(tmp_path / "out.md"))
    assert result["status"] == "error"


def test_doc_lint_no_warnings(tmp_path):
    from modules.doc.src.doc import doc_lint
    (tmp_path / "README.md").write_text("# Title\n\nSome content.\n")
    result = doc_lint(docs_dir=str(tmp_path))
    assert result["status"] == "ok"
    assert result["files_checked"] == 1


def test_doc_lint_missing_dir():
    from modules.doc.src.doc import doc_lint
    result = doc_lint(docs_dir="/nonexistent")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Resource module
# ---------------------------------------------------------------------------

def test_resource_pack_unpack(tmp_path):
    from modules.resource.src.resource import resource_pack, resource_unpack, resource_list
    # Create source dir with a few files
    src = tmp_path / "resources"
    src.mkdir()
    (src / "sprite.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (src / "level.json").write_text('{"level": 1}')
    bundle = str(tmp_path / "game.rpk")
    pack_result = resource_pack(input_dir=str(src), output=bundle)
    assert pack_result["status"] == "ok"
    assert pack_result["resource_count"] == 2

    lst = resource_list(bundle=bundle)
    assert lst["status"] == "ok"
    assert lst["count"] == 2

    out_dir = str(tmp_path / "unpacked")
    unpack_result = resource_unpack(bundle=bundle, output_dir=out_dir)
    assert unpack_result["status"] == "ok"
    assert Path(out_dir, "sprite.png").exists()
    assert Path(out_dir, "level.json").exists()


def test_resource_add_remove(tmp_path):
    from modules.resource.src.resource import resource_pack, resource_add, resource_remove, resource_list
    src = tmp_path / "resources"
    src.mkdir()
    (src / "a.txt").write_text("a")
    bundle = str(tmp_path / "res.rpk")
    resource_pack(input_dir=str(src), output=bundle)

    new_file = tmp_path / "b.txt"
    new_file.write_text("b")
    add_result = resource_add(bundle=bundle, path=str(new_file), alias="b.txt")
    assert add_result["status"] == "ok"

    lst = resource_list(bundle=bundle)
    assert lst["count"] == 2

    remove_result = resource_remove(bundle=bundle, name="b.txt")
    assert remove_result["status"] == "ok"

    lst2 = resource_list(bundle=bundle)
    assert lst2["count"] == 1


def test_resource_missing_bundle():
    from modules.resource.src.resource import resource_list
    result = resource_list(bundle="/nonexistent/bundle.rpk")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Package module
# ---------------------------------------------------------------------------

def test_pkg_list_pip():
    from modules.package.src.package import pkg_list
    result = pkg_list(manager="pip")
    assert result["status"] == "ok"
    assert "packages" in result


def test_pkg_install_real_package():
    from modules.package.src.package import pkg_install
    # Install a tiny, always-available package
    result = pkg_install(name="pip", manager="pip")
    # pip install pip should succeed (already installed)
    assert result["status"] == "ok"


def test_pkg_update_pip():
    from modules.package.src.package import pkg_update
    result = pkg_update(name="pip", manager="pip")
    assert result["status"] == "ok"


def test_pkg_install_unsupported_manager():
    from modules.package.src.package import pkg_install
    result = pkg_install(name="somepkg", manager="unknown_manager")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Binary module
# ---------------------------------------------------------------------------

def test_binary_info_python_exe():
    import sys
    from modules.binary.src.binary import binary_info
    result = binary_info(path=sys.executable)
    assert result["status"] == "ok"
    assert result["size_bytes"] > 0
    assert "entropy" in result
    assert "format" in result


def test_binary_info_missing():
    from modules.binary.src.binary import binary_info
    result = binary_info(path="/nonexistent/binary")
    assert result["status"] == "error"


def test_binary_hex_dump(tmp_path):
    from modules.binary.src.binary import binary_hex
    f = tmp_path / "data.bin"
    f.write_bytes(bytes(range(64)))
    result = binary_hex(path=str(f), offset=0, length=32)
    assert result["status"] == "ok"
    assert "hex_dump" in result
    assert "00" in result["hex_dump"]


def test_binary_hex_offset_beyond_file(tmp_path):
    from modules.binary.src.binary import binary_hex
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00" * 8)
    result = binary_hex(path=str(f), offset=100)
    assert result["status"] == "error"


def test_binary_strings_extract(tmp_path):
    from modules.binary.src.binary import binary_strings
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00\x01HelloWorld\x00\x00ShortX\x00LongStringHere\x00")
    result = binary_strings(path=str(f), min_length=4)
    assert result["status"] == "ok"
    assert any("HelloWorld" in s for s in result["strings"])


def test_binary_disasm(tmp_path):
    from modules.binary.src.binary import binary_disasm
    f = tmp_path / "data.bin"
    f.write_bytes(bytes(range(32)))
    result = binary_disasm(path=str(f), offset=0, length=16)
    assert result["status"] == "ok"
    assert "listing" in result


def test_binary_patch_and_verify(tmp_path):
    from modules.binary.src.binary import binary_patch, binary_hex
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00" * 16)
    result = binary_patch(path=str(f), offset=4, data="deadbeef")
    assert result["status"] == "ok"
    assert Path(str(f) + ".bak").exists()
    # Verify the patch
    content = f.read_bytes()
    assert content[4:8] == bytes.fromhex("deadbeef")


def test_binary_patch_invalid_hex(tmp_path):
    from modules.binary.src.binary import binary_patch
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00" * 8)
    result = binary_patch(path=str(f), offset=0, data="ZZZZ")
    assert result["status"] == "error"


def test_binary_patch_out_of_range(tmp_path):
    from modules.binary.src.binary import binary_patch
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00" * 4)
    result = binary_patch(path=str(f), offset=10, data="ff")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Scaffold module
# ---------------------------------------------------------------------------

def test_scaffold_module_creates_files(tmp_path, monkeypatch):
    import sys
    # Point _repo_root at tmp_path so we don't pollute the real modules/ dir
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "modules").mkdir(exist_ok=True)
    (tmp_path / "plugins").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)

    from modules.scaffold.src import scaffold_tools
    monkeypatch.setattr(scaffold_tools, "_repo_root", lambda: tmp_path)

    result = scaffold_tools.scaffold_module("test_mod", "A test module")
    assert result["status"] == "created"
    assert result["module"] == "test_mod"
    assert (tmp_path / "modules" / "test_mod" / "module.json").exists()
    assert (tmp_path / "modules" / "test_mod" / "tools.json").exists()
    assert (tmp_path / "modules" / "test_mod" / "src" / "test_mod_tools.py").exists()


def test_scaffold_module_duplicate_fails(tmp_path, monkeypatch):
    from modules.scaffold.src import scaffold_tools
    monkeypatch.setattr(scaffold_tools, "_repo_root", lambda: tmp_path)
    (tmp_path / "modules" / "dupe").mkdir(parents=True, exist_ok=True)

    result = scaffold_tools.scaffold_module("dupe", "Already exists")
    assert "error" in result


def test_scaffold_plugin_creates_files(tmp_path, monkeypatch):
    from modules.scaffold.src import scaffold_tools
    monkeypatch.setattr(scaffold_tools, "_repo_root", lambda: tmp_path)
    (tmp_path / "plugins").mkdir(exist_ok=True)

    result = scaffold_tools.scaffold_plugin("my_plugin", "A plugin")
    assert result["status"] == "created"
    assert (tmp_path / "plugins" / "my_plugin" / "plugin.json").exists()


def test_scaffold_tests_creates_file(tmp_path, monkeypatch):
    import json
    from modules.scaffold.src import scaffold_tools
    monkeypatch.setattr(scaffold_tools, "_repo_root", lambda: tmp_path)

    # Create a fake module with tools.json
    mod_dir = tmp_path / "modules" / "fake_mod"
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / "tools.json").write_text(json.dumps([
        {"name": "fake_run", "description": "runs", "function": "modules.fake_mod.src.fake_mod_tools.fake_run",
         "arguments": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}}
    ]))
    (tmp_path / "tests").mkdir(exist_ok=True)

    result = scaffold_tools.scaffold_tests("fake_mod")
    assert result["status"] == "created"
    assert result["tests_count"] == 1
    test_file = tmp_path / result["test_file"]
    assert test_file.exists()
    content = test_file.read_text()
    assert "def test_fake_run" in content


def test_scaffold_tests_module_not_found(tmp_path, monkeypatch):
    from modules.scaffold.src import scaffold_tools
    monkeypatch.setattr(scaffold_tools, "_repo_root", lambda: tmp_path)
    (tmp_path / "modules").mkdir(exist_ok=True)
    (tmp_path / "plugins").mkdir(exist_ok=True)

    result = scaffold_tools.scaffold_tests("nonexistent_mod")
    assert "error" in result
