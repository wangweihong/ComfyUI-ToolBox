"""Cooperative resource checks, not a guarantee against instantaneous OOM."""
import shutil
import threading
import time
from pathlib import Path

GIB = 2**30


class Resources:
    def __init__(self, config, directory, interrupt=lambda: None):
        import psutil
        self.psutil = psutil
        self.process = psutil.Process()
        self.cfg, self.directory, self.interrupt = config, Path(directory), interrupt
        self.error = None
        self.stop = threading.Event()
        self.peak = dict(process_tree_rss_gib=0., gpu_process_peak_gib=None,
                         gpu_total_peak_gib=None, torch_allocated_peak_gib=None, torch_reserved_peak_gib=None)
        self.min_available = None
        self.started = time.monotonic()
        self.thread = None
        self.output_directory = None
        self.nvml = self.gpu = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self.nvml = pynvml
            self.gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            pass

    def sample(self):
        try:
            vm = self.psutil.virtual_memory()
            processes = [self.process] + self.process.children(recursive=True)
            rss = sum(p.memory_info().rss for p in processes if p.is_running()) / GIB
            self.peak["process_tree_rss_gib"] = max(self.peak["process_tree_rss_gib"], rss)
            available = vm.available/GIB
            self.min_available = available if self.min_available is None else min(self.min_available, available)
            if available < self.cfg["memory_reserve_gib"]:
                self.error = "Available RAM fell below the reserve. Reduce chunk_frames/tile size or use disk tile storage."
            if self.cfg["memory_budget_gib"] and rss > self.cfg["memory_budget_gib"]:
                self.error = "ComfyUI process-tree RSS exceeded memory_budget_gib (includes existing nodes/shared mappings)."
            free = shutil.disk_usage(self.directory).free
            if free < self.cfg["disk_reserve_gib"]*GIB:
                self.error = "Cache filesystem has insufficient free space; clear owned caches or choose another directory."
            if self.output_directory and shutil.disk_usage(self.output_directory).free < self.cfg['disk_reserve_gib']*GIB:
                self.error = 'Video destination filesystem fell below disk_reserve_gib.'
            if self.cfg["disk_budget_gib"]:
                used = sum(p.stat().st_size for p in self.directory.rglob('*') if p.is_file())
                if used > self.cfg["disk_budget_gib"]*GIB:
                    self.error = "Cache exceeds disk_budget_gib. No automatic cache-mode switch was performed."
            if self.nvml and self.gpu is not None:
                total = self.nvml.nvmlDeviceGetMemoryInfo(self.gpu).used/GIB
                self.peak["gpu_total_peak_gib"] = max(self.peak["gpu_total_peak_gib"] or 0., total)
                # NVML may expose host PIDs inside a container. Do not present an
                # allocator estimate as a reliable NVML process measurement.
                gpu_processes = self.nvml.nvmlDeviceGetComputeRunningProcesses(self.gpu)
                ids = {p.pid for p in processes}
                if any(p.pid == self.process.pid for p in gpu_processes):
                    own = sum(p.usedGpuMemory for p in gpu_processes if p.pid in ids and p.usedGpuMemory is not None)/GIB
                    self.peak["gpu_process_peak_gib"] = max(self.peak["gpu_process_peak_gib"] or 0., own)
        except (self.psutil.NoSuchProcess, FileNotFoundError, ProcessLookupError):
            pass

    def __enter__(self):
        import torch
        if torch.cuda.is_initialized():
            torch.cuda.reset_peak_memory_stats()
        self.sample()
        try:
            self.check()
        except BaseException:
            if self.nvml:self.nvml.nvmlShutdown()
            raise
        def run():
            while not self.stop.wait(.2):
                self.sample()
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return self

    def check(self):
        self.interrupt()
        if self.error:
            raise RuntimeError(self.error)

    def __exit__(self, *exc):
        self.stop.set()
        if self.thread:
            self.thread.join(2)
        self.sample()
        try:
            import torch
            if torch.cuda.is_initialized():
                self.peak["torch_allocated_peak_gib"] = torch.cuda.max_memory_allocated()/GIB
                self.peak["torch_reserved_peak_gib"] = torch.cuda.max_memory_reserved()/GIB
        except ImportError:
            pass
        if self.nvml:
            self.nvml.nvmlShutdown()
        if not exc[0] and self.error:
            raise RuntimeError(self.error)

    def info(self):
        return dict(**self.peak, system_min_available_gib=self.min_available,
                    limits={k:self.cfg[k] for k in ('memory_budget_gib','memory_reserve_gib','disk_budget_gib','disk_reserve_gib')},
                    sampling_interval_seconds=.2, wall_seconds=time.monotonic()-self.started,
                    scope="Current ComfyUI process tree; RSS includes shared mappings. GPU total includes other apps. "
                          "NVML process value is null when host/container PIDs cannot be mapped; Torch allocator peaks are separate.")


def preflight(plan, directory):
    import psutil
    cfg = plan["config"]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(directory).free
    estimate = plan["estimates"]
    staging = estimate["tile_cache_peak_bytes"] if cfg["tile_storage"] == "disk" else 0
    required = staging + (estimate["raw_frame_cache_bytes"] if cfg["cache_mode"] == "raw" else 0)
    if free < required + cfg["disk_reserve_gib"]*GIB:
        raise RuntimeError(f"Estimated raw/tile cache needs {required/GIB:.2f} GiB plus disk reserve; free {free/GIB:.2f} GiB. Change mode/frames/storage/directory explicitly.")
    if cfg["disk_budget_gib"] and required > cfg["disk_budget_gib"]*GIB:
        raise RuntimeError("Estimated raw/tile cache exceeds disk_budget_gib. Increase budget or choose another configuration.")
    working = estimate["image_working_bytes"]
    if cfg["tile_storage"] == "ram":
        working += estimate["tile_cache_peak_bytes"]
    if psutil.virtual_memory().available < working + cfg["memory_reserve_gib"]*GIB:
        raise RuntimeError("Estimated image buffers exceed available RAM. Reduce chunk_frames/tile size or use disk tile storage.")
    if cfg["memory_budget_gib"] and psutil.Process().memory_info().rss + working > cfg["memory_budget_gib"]*GIB:
        raise RuntimeError("Estimated process + image buffers exceed memory_budget_gib; model/decoder overhead is additional.")
    return dict(disk_free_bytes=free, estimated_required_disk_bytes=required,
                note="FFV1 size depends on content. Estimates exclude variable model/driver overhead; runtime monitoring is cooperative.")
