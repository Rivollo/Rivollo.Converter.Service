import asyncio
import logging
import os
import subprocess

from core.config import settings

logger = logging.getLogger(__name__)

_SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "blender_scripts",
    "glb_to_usdz.py",
)


async def run_blender_conversion(glb_path: str, usdz_path: str, job_id: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_blender_sync, glb_path, usdz_path, job_id)


def _run_blender_sync(glb_path: str, usdz_path: str, job_id: str) -> None:
    cmd = [
        settings.blender_bin,
        "--background",
        "--python", _SCRIPT_PATH,
        "--",
        "--input", glb_path,
        "--output", usdz_path,
    ]

    logger.info(f"[Job {job_id}] Blender command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"[Job {job_id}] Blender timed out after 300 seconds") from exc

    if result.stdout:
        logger.info(f"[Job {job_id}] Blender stdout:\n{result.stdout}")
    if result.stderr:
        logger.warning(f"[Job {job_id}] Blender stderr:\n{result.stderr}")

    if result.returncode != 0:
        if result.returncode == -9:
            raise RuntimeError(
                f"[Job {job_id}] Blender was killed by the OS (SIGKILL / OOM). "
                f"The container ran out of memory during conversion. "
                f"Increase the container memory limit."
            )
        raise RuntimeError(
            f"[Job {job_id}] Blender exited with code {result.returncode}. "
            f"stderr: {result.stderr[-2000:]}"
        )

    logger.info(f"[Job {job_id}] Blender process completed successfully")
