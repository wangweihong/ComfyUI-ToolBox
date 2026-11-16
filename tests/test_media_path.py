"""Run in an existing ComfyUI Python environment; no models are loaded."""

import asyncio
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

COMFY = Path(os.environ.get("COMFY_ROOT", "/root/ComfyUI"))
try:
    has_comfy = (COMFY / "folder_paths.py").is_file()
except OSError:
    has_comfy = False
if not has_comfy:
    pytest.skip("Requires the existing ComfyUI Python environment", allow_module_level=True)
sys.path.append(str(COMFY))
import comfy.cli_args

comfy.cli_args.args.cpu = True

import av
import execution
import nodes as core_nodes
import torch
from comfy_api.input_impl import VideoFromFile
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("toolbox_media_path_test", ROOT / "nodes/media_path_nodes.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
VideoNode = module.ToolBoxLoadVideoPath
AudioNode = module.ToolBoxLoadAudioPath
image_spec = importlib.util.spec_from_file_location("toolbox_image_path_test", ROOT / "nodes/image_path_nodes.py")
image_module = importlib.util.module_from_spec(image_spec)
image_spec.loader.exec_module(image_module)
ImageNode = image_module.ToolBoxLoadImagePath


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "2", *map(str, args)], check=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp("路径 media")
    Image.new("RGB", (9, 6), "red").save(root / "图片.png")
    wav = root / "音频.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.5",
           "-ac", "2", "-c:a", "pcm_s16le", wav)
    silent = root / "silent.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=160x96:r=12:d=0.5", "-an",
           "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p", silent)
    video = root / "视频.mp4"
    ffmpeg("-i", silent, "-i", wav, "-c:v", "copy", "-c:a", "aac", "-shortest", video)
    for suffix, codec in [("flac", "flac"), ("mp3", "libmp3lame"), ("m4a", "aac")]:
        ffmpeg("-i", wav, "-c:a", codec, root / ("音频." + suffix))
    return root


@pytest.mark.parametrize("filename", ["silent.mp4", "视频.mp4"])
def test_video_is_file_backed_and_metadata_does_not_decode_frames(media, monkeypatch, filename):
    path = media / filename
    original = path.read_bytes()
    files = set(media.iterdir())

    def fail_materialization(*args, **kwargs):
        pytest.fail("Loading metadata must not materialize the video")

    monkeypatch.setattr(VideoFromFile, "get_components", fail_materialization)
    video, width, height, fps, duration = VideoNode.execute(str(path)).result
    assert isinstance(video, VideoFromFile)
    assert video.get_stream_source() == str(path.resolve())
    assert (width, height) == (160, 96)
    assert fps == pytest.approx(12)
    assert duration == pytest.approx(0.5)
    assert path.read_bytes() == original
    assert set(media.iterdir()) == files


def test_standard_video_components_can_be_extracted(media):
    video = VideoNode.execute(str(media / "视频.mp4"))[0]
    components = video.get_components()
    assert components.images.shape == (6, 96, 160, 3)
    assert float(components.frame_rate) == 12
    assert components.audio["sample_rate"] == 48000
    assert components.audio["waveform"].shape[:2] == (1, 2)


@pytest.mark.parametrize("filename", ["音频.wav", "音频.flac", "音频.mp3", "音频.m4a", "视频.mp4"])
def test_audio_formats_and_video_track_preserve_rate_and_channels(media, filename):
    path = media / filename
    original = path.read_bytes()
    audio, sample_rate, duration = AudioNode.execute(str(path)).result
    waveform = audio["waveform"]
    assert waveform.shape[:2] == (1, 2)
    assert waveform.dtype == torch.float32
    assert torch.isfinite(waveform).all()
    assert waveform.abs().max() > 0
    assert sample_rate == audio["sample_rate"] == 48000
    assert duration == waveform.shape[-1] / sample_rate
    assert duration == pytest.approx(0.5, abs=0.08)
    assert path.read_bytes() == original


def test_audio_rejects_silent_video(media):
    with pytest.raises(ValueError, match="No audio stream"):
        AudioNode.execute(str(media / "silent.mp4"))


@pytest.mark.parametrize("node,filename", [(VideoNode, "视频.mp4"), (AudioNode, "音频.wav")])
def test_path_resolution_validation_and_changes(media, tmp_path, monkeypatch, node, filename):
    monkeypatch.chdir(media)
    assert node.validate_inputs(filename) is True
    assert node.validate_inputs(None) is True
    assert node.validate_inputs() is True
    assert math.isnan(node.fingerprint_inputs(None))
    node.execute("  " + filename + "  ")
    for path in ["", "  ", str(tmp_path), str(tmp_path / "missing")]:
        assert isinstance(node.validate_inputs(path), str)
        assert math.isnan(node.fingerprint_inputs(path))
        with pytest.raises(ValueError):
            node.execute(path)
    source = tmp_path / filename
    source.write_bytes((media / filename).read_bytes())
    fingerprint = node.fingerprint_inputs(str(source))
    assert fingerprint == node.fingerprint_inputs(str(source))
    stat = source.stat()
    data = bytearray(source.read_bytes())
    data[-1] ^= 1
    source.write_bytes(data)
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert source.stat().st_size == stat.st_size
    assert fingerprint != node.fingerprint_inputs(str(source))
    corrupt = tmp_path / "corrupt.bin"
    corrupt.write_bytes(b"not media")
    with pytest.raises((av.error.FFmpegError, ValueError)):
        node.execute(str(corrupt))


@pytest.mark.parametrize("node,filename", [(VideoNode, "视频.mp4"), (AudioNode, "音频.wav"), (ImageNode, "图片.png")])
def test_native_executor_validates_connected_path(media, monkeypatch, node, filename):
    class PathSource:
        RETURN_TYPES = ("STRING",)

        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"text": ("STRING", {})}}

    node_id = node.__name__
    monkeypatch.setitem(core_nodes.NODE_CLASS_MAPPINGS, "TestPathSource", PathSource)
    monkeypatch.setitem(core_nodes.NODE_CLASS_MAPPINGS, node_id, node)
    prompt = {
        "1": {"class_type": "TestPathSource", "inputs": {"text": str(media / filename)}},
        "2": {"class_type": node_id, "inputs": {"path": ["1", 0]}},
    }
    result = asyncio.run(execution.validate_inputs("tb-media-path-test", prompt, "2", {}))
    assert result[0] is True, result[1]


def test_registration_schema_and_locales():
    for node_id, node, outputs in [
        ("ToolBoxLoadVideoPath", VideoNode, ["VIDEO", "INT", "INT", "FLOAT", "FLOAT"]),
        ("ToolBoxLoadAudioPath", AudioNode, ["AUDIO", "INT", "FLOAT"]),
    ]:
        assert module.NODE_CLASS_MAPPINGS[node_id] is node
        info = node.GET_NODE_INFO_V1()
        assert info["output"] == outputs
        assert set(info["input"]["required"]) == {"path"}
        for language in ["en", "zh"]:
            entry = json.loads((ROOT / f"locales/{language}/nodeDefs.json").read_text())[node_id]
            assert entry["display_name"] == module.NODE_DISPLAY_NAME_MAPPINGS[node_id]
            assert set(entry["outputs"]) == {str(i) for i in range(len(outputs))}
