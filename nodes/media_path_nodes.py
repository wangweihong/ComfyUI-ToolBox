"""Load server video and audio files through ComfyUI's native media APIs."""

from pathlib import Path

from comfy_api.input_impl import VideoFromFile
from comfy_api.latest import io
from comfy_extras.nodes_audio import load as load_audio


def _media_path(path):
    if not isinstance(path, str):
        raise ValueError("Media path must be a string.")
    value = path.strip()
    if not value:
        raise ValueError("Media path cannot be empty.")
    source = Path(value).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Media file does not exist: {source}")
    return source


class _MediaPathNode(io.ComfyNode):
    @classmethod
    def validate_inputs(cls, path=None):
        # Linked values are unavailable during ComfyUI prompt validation.
        if path is None:
            return True
        try:
            _media_path(path)
        except (ValueError, OSError) as error:
            return str(error)
        return True

    @classmethod
    def fingerprint_inputs(cls, path):
        try:
            source = _media_path(path)
            stat = source.stat()
            # Avoid reading entire videos merely to check the execution cache.
            return str(source), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
        except (ValueError, OSError):
            return float("nan")


class ToolBoxLoadVideoPath(_MediaPathNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="ToolBoxLoadVideoPath",
            display_name="tb-load-video-path",
            category="eazy-toolbox/video",
            description="Load a server video by path without copying or decoding all frames. Connect VIDEO to Get Video Components when frames or audio are needed.",
            inputs=[io.String.Input(
                "path", default="", multiline=False,
                tooltip="Server video path. Enter an absolute path or connect the media library path output.",
            )],
            outputs=[
                io.Video.Output("video"),
                io.Int.Output("width"),
                io.Int.Output("height"),
                io.Float.Output("fps"),
                io.Float.Output("duration"),
            ],
        )

    @classmethod
    def execute(cls, path):
        video = VideoFromFile(str(_media_path(path)))
        width, height = video.get_dimensions()
        return io.NodeOutput(video, width, height, float(video.get_frame_rate()), float(video.get_duration()))


class ToolBoxLoadAudioPath(_MediaPathNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="ToolBoxLoadAudioPath",
            display_name="tb-load-audio-path",
            category="eazy-toolbox/audio",
            description="Load audio from a server file path, preserving the native sample rate and channels. Also accepts video files with an audio track.",
            inputs=[io.String.Input(
                "path", default="", multiline=False,
                tooltip="Server audio path. Enter an absolute path or connect the media library path output.",
            )],
            outputs=[
                io.Audio.Output("audio"),
                io.Int.Output("sample_rate"),
                io.Float.Output("duration"),
            ],
        )

    @classmethod
    def execute(cls, path):
        waveform, sample_rate = load_audio(str(_media_path(path)))
        audio = {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}
        return io.NodeOutput(audio, sample_rate, waveform.shape[-1] / sample_rate)


NODE_CLASS_MAPPINGS = {
    "ToolBoxLoadVideoPath": ToolBoxLoadVideoPath,
    "ToolBoxLoadAudioPath": ToolBoxLoadAudioPath,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ToolBoxLoadVideoPath": "tb-load-video-path",
    "ToolBoxLoadAudioPath": "tb-load-audio-path",
}
