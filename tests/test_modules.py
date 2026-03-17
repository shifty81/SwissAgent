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
