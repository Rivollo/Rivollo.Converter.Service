import argparse
import asyncio
import logging
import os
import shutil
import sys
import tempfile

from core.config import settings
from core.logging import setup_logging
from db.session import SessionLocal
from services.blob_service import download_glb, upload_usdz
from services.blender_service import run_blender_conversion
from services.callback_service import post_callback
from services.db_service import save_usdz_asset, update_product_status

setup_logging()
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="USDZ Converter Job")
    parser.add_argument("--job-id",           required=False, default=None)
    parser.add_argument("--glb-blob-url",     required=True)
    parser.add_argument("--output-blob-name", required=True)
    parser.add_argument("--product-id",       required=True)
    parser.add_argument("--user-id",          required=True)
    parser.add_argument("--product-name",     required=True)
    parser.add_argument("--callback-url",     required=False, default=None)
    return parser.parse_args()


async def run_job() -> None:
    args = parse_args()

    job_id           = args.job_id
    glb_blob_url     = args.glb_blob_url
    output_blob_name = args.output_blob_name
    product_id       = args.product_id
    user_id          = args.user_id
    product_name     = args.product_name
    callback_url     = args.callback_url

    logger.info(f"[Job {job_id}] Starting — product={product_id} user={user_id}")

    tmp_dir = tempfile.mkdtemp(prefix=f"job_{job_id}_")
    
    try:
        glb_path  = os.path.join(tmp_dir, "model.glb")
        usdz_path = os.path.join(tmp_dir, "model.usdz")

        logger.info(f"[Job {job_id}] Downloading GLB from {glb_blob_url}")
        await download_glb(glb_blob_url, glb_path)

        logger.info(f"[Job {job_id}] Running Blender conversion")
        await run_blender_conversion(glb_path, usdz_path, job_id)

        if not os.path.exists(usdz_path):
            raise FileNotFoundError(f"USDZ file not produced at {usdz_path}")

        blob_path = f"{user_id}/{product_id}/{output_blob_name}"
        logger.info(f"[Job {job_id}] Uploading USDZ as {blob_path}")
        usdz_url = await upload_usdz(usdz_path, blob_path)

        logger.info(f"[Job {job_id}] Conversion succeeded — {usdz_url}")

        blob_url = f"{settings.azure_blob_base_url.rstrip('/')}/{settings.storage_container}/{blob_path}"

        db = SessionLocal()
        try:
            save_usdz_asset(db, blob_url, usdz_path, product_id, user_id, product_name)
            update_product_status(db, product_id, "READY")
        finally:
            db.close()

        if callback_url:
            await post_callback(callback_url, {
                "job_id": job_id,
                "status": "success",
                "usdz_blob_url": usdz_url,
            })

    except Exception as exc:
        logger.error(f"[Job {job_id}] Conversion failed: {exc}", exc_info=True)
        if callback_url:
            await post_callback(callback_url, {
                "job_id": job_id,
                "status": "failed",
                "error": str(exc),
            })
        sys.exit(1)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.info(f"[Job {job_id}] Cleaned up tmp_dir")


if __name__ == "__main__":
    asyncio.run(run_job())
