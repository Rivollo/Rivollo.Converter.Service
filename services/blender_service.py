import asyncio
import logging
import os
import shutil
import signal
import subprocess

try:
    import resource
except ImportError:          # not available on Windows
    resource = None

from core.config import settings

logger = logging.getLogger(__name__)

_SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "blender_scripts",
    "glb_to_usdz.py",
)

_CGROUP_V2 = "/sys/fs/cgroup"
_CGROUP_V1 = "/sys/fs/cgroup/memory"


def _read_first(*paths) -> str:
    """Return the first readable file's stripped contents, or None."""
    for path in paths:
        try:
            with open(path) as f:
                return f.read().strip()
        except OSError:
            continue
    return None


def _mb(raw: str) -> str:
    """Format a cgroup byte value as MB, passing through 'max' and None."""
    if raw is None:
        return "unknown"
    if raw == "max":
        return "max (unlimited)"
    try:
        return f"{int(raw) // (1024 * 1024)} MB"
    except ValueError:
        return raw


def _memory_stats() -> dict:
    """The memory limit and usage this container actually has, per the kernel."""
    return {
        "limit": _read_first(f"{_CGROUP_V2}/memory.max",
                             f"{_CGROUP_V1}/memory.limit_in_bytes"),
        "current": _read_first(f"{_CGROUP_V2}/memory.current",
                               f"{_CGROUP_V1}/memory.usage_in_bytes"),
        "peak": _read_first(f"{_CGROUP_V2}/memory.peak"),
    }


def _oom_kill_count() -> int:
    """How many times the kernel OOM killer fired in this cgroup, or None.

    This is the only definitive answer to "was it an OOM?" - a SIGKILL on its
    own does not tell us that.
    """
    events = _read_first(f"{_CGROUP_V2}/memory.events",
                         f"{_CGROUP_V1}/memory.oom_control")
    if not events:
        return None
    for line in events.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "oom_kill":
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def _child_peak_rss_mb() -> str:
    """Peak RSS of finished child processes (i.e. Blender), in MB."""
    if resource is None:
        return "unknown"
    return f"{resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024} MB"


def _disk_free(path: str) -> str:
    """Free space on the filesystem holding path - ephemeral storage check."""
    try:
        usage = shutil.disk_usage(path)
        return (f"{usage.free // (1024 * 1024)} MB free "
                f"of {usage.total // (1024 * 1024)} MB")
    except OSError:
        return "unknown"


def _signal_name(sig: int) -> str:
    try:
        return signal.Signals(sig).name
    except ValueError:
        return f"signal {sig}"


async def run_blender_conversion(glb_path: str, usdz_path: str, job_id: str, bake_resolution: int,) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_blender_sync, glb_path, usdz_path, job_id, bake_resolution)


def _run_blender_sync(glb_path: str, usdz_path: str, job_id: str, bake_resolution: int) -> None:
    cmd = [
        settings.blender_bin,
        "--background",
        "--python", _SCRIPT_PATH,
        "--",
        "--input", glb_path,
        "--output", usdz_path,
        "--bake-resolution", str(bake_resolution),
    ]

    logger.info(f"[Job {job_id}] Blender command: {' '.join(cmd)}")

    before = _memory_stats()
    oom_before = _oom_kill_count()
    logger.info(
        f"[Job {job_id}] Container memory limit={_mb(before['limit'])} "
        f"current={_mb(before['current'])}; "
        f"tmp disk {_disk_free(os.path.dirname(usdz_path))}; "
        f"oom_kill count={oom_before}"
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"[Job {job_id}] Blender timed out after 300 seconds") from exc

    after = _memory_stats()
    oom_after = _oom_kill_count()
    blender_peak = _child_peak_rss_mb()
    logger.info(
        f"[Job {job_id}] Blender exited {result.returncode}; "
        f"Blender peak RSS={blender_peak}; "
        f"cgroup peak={_mb(after['peak'])} of limit={_mb(after['limit'])}; "
        f"tmp disk {_disk_free(os.path.dirname(usdz_path))}; "
        f"oom_kill count={oom_before} -> {oom_after}"
    )

    if result.stdout:
        logger.info(f"[Job {job_id}] Blender stdout:\n{result.stdout}")
    if result.stderr:
        logger.warning(f"[Job {job_id}] Blender stderr:\n{result.stderr}")

    if result.returncode != 0:
        # A negative return code means Blender was killed by a signal. Report what
        # the kernel actually says rather than assuming the cause: SIGKILL alone
        # does not mean OOM, and oom_kill is the only field that settles it.
        if result.returncode < 0:
            if oom_before is None or oom_after is None:
                oom_verdict = "unknown (cgroup memory.events unreadable)"
            elif oom_after > oom_before:
                oom_verdict = f"YES ({oom_before} -> {oom_after})"
            else:
                oom_verdict = f"NO (count unchanged at {oom_after})"

            sig = -result.returncode
            raise RuntimeError(
                f"[Job {job_id}] Blender was killed by {_signal_name(sig)}. "
                f"Kernel OOM killer fired: {oom_verdict}. "
                f"Blender peak RSS={blender_peak}, "
                f"cgroup peak={_mb(after['peak'])}, limit={_mb(after['limit'])}, "
                f"tmp disk {_disk_free(os.path.dirname(usdz_path))}. "
                f"stderr: {result.stderr[-2000:]}"
            )

        raise RuntimeError(
            f"[Job {job_id}] Blender exited with code {result.returncode}. "
            f"stderr: {result.stderr[-2000:]}"
        )

    logger.info(f"[Job {job_id}] Blender process completed successfully")

    if not os.path.exists(usdz_path):
        logger.error(f"[Job {job_id}] Blender stdout:\n{result.stdout[-500:]}")
        raise RuntimeError(
            f"[Job {job_id}] Blender exited 0 but did not create the USDZ file: {usdz_path}"
        )

    logger.info(f"[Job {job_id}] USDZ file verified ({os.path.getsize(usdz_path)} bytes)")