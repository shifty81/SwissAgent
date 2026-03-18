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

