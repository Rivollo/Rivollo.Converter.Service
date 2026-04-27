"""
Blender Service

Wraps Blender headless mode to convert a local .glb file to .usdz.
Blender path can be overridden via the BLENDER_BIN environment variable.
"""

import asyncio
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

# Absolute path to the Blender Python script
_BLENDER_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "blender_scripts", "glb_to_usdz.py"
)

# Blender executable — override via env var if installed in a non-default path
BLENDER_BIN = os.environ.get("BLENDER_BIN", "blender")


def convert_glb_to_usdz(glb_path: str, usdz_path: str) -> str:
    """
    Convert a local GLB file to USDZ using Blender in headless mode.

    Args:
        glb_path:  Path to the source .glb file (must exist).
        usdz_path: Desired output path for the .usdz file.

    Returns:
        usdz_path on success.

    Raises:
        RuntimeError: If Blender exits with a non-zero return code.
        FileNotFoundError: If glb_path does not exist.
    """
    if not os.path.exists(glb_path):
        raise FileNotFoundError(f"GLB file not found: {glb_path}")

    cmd = [
        BLENDER_BIN,
        "--background",
        "--python", _BLENDER_SCRIPT,
        "--",
        "--input", glb_path,
        "--output", usdz_path,
    ]

    logger.info(f"[USDZ] Starting Blender conversion: {glb_path} → {usdz_path}")
    logger.debug(f"[USDZ] Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,  # 2-minute safety timeout
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Blender GLB→USDZ conversion timed out after 120 seconds.")

    if result.returncode != 0:
        logger.error(f"[USDZ] Blender stderr:\n{result.stderr}")
        raise RuntimeError(
            f"Blender GLB→USDZ conversion failed (exit code {result.returncode}).\n"
            f"stderr: {result.stderr[-500:]}"  # last 500 chars to avoid log flooding
        )

    logger.info(f"[USDZ] Conversion successful → {usdz_path}")

    # Verify the file was actually created — Blender can exit 0 without writing output
    if not os.path.exists(usdz_path):
        logger.error(f"[USDZ] Blender stdout:\n{result.stdout[-500:]}")
        raise RuntimeError(
            f"Blender exited 0 but did not create the USDZ file: {usdz_path}"
        )

    logger.info(f"[USDZ] File verified ({os.path.getsize(usdz_path)} bytes)")
    return usdz_path


async def run_blender_conversion(glb_path: str, usdz_path: str, job_id: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, convert_glb_to_usdz, glb_path, usdz_path)
