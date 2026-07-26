"""Tests for content-hash idempotency."""

from broadside.render.hasher import content_hash, scene_filename, scene_exists
from pathlib import Path
import tempfile


def test_content_hash_deterministic():
    h1 = content_hash("Hello world", "avatar_1", "voice_1")
    h2 = content_hash("Hello world", "avatar_1", "voice_1")
    assert h1 == h2
    assert len(h1) == 12


def test_content_hash_changes_with_text():
    h1 = content_hash("Hello world", "avatar_1", "voice_1")
    h2 = content_hash("Different text", "avatar_1", "voice_1")
    assert h1 != h2


def test_content_hash_changes_with_avatar():
    h1 = content_hash("Hello world", "avatar_1", "voice_1")
    h2 = content_hash("Hello world", "avatar_2", "voice_1")
    assert h1 != h2


def test_scene_filename_format():
    name = scene_filename("s1", "abc123def456")
    assert name == "s1-abc123def456.mp4"


def test_scene_exists_false():
    assert scene_exists("ep01", "s1", "abc123", Path("/nonexistent")) is False


def test_scene_exists_true():
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        scene_dir = build / "ep01" / "scenes"
        scene_dir.mkdir(parents=True)
        (scene_dir / "s1-abc123def456.mp4").write_bytes(b"fake video")
        assert scene_exists("ep01", "s1", "abc123def456", build) is True
