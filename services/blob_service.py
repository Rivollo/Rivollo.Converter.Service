import asyncio
import logging

from azure.storage.blob import BlobClient, BlobServiceClient, ContentSettings

from core.config import settings

logger = logging.getLogger(__name__)


async def download_glb(blob_url: str, dest_path: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _download_glb_sync, blob_url, dest_path)


def _download_glb_sync(blob_url: str, dest_path: str) -> None:
    client = BlobClient.from_blob_url(blob_url)
    with open(dest_path, "wb") as f:
        client.download_blob().readinto(f)
    logger.debug(f"Downloaded GLB to {dest_path}")


async def upload_usdz(local_path: str, blob_name: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _upload_usdz_sync, local_path, blob_name)


def _upload_usdz_sync(local_path: str, blob_name: str) -> str:
    service_client = BlobServiceClient.from_connection_string(settings.azure_storage_conn_string)
    blob_client = service_client.get_container_client(settings.storage_container).get_blob_client(blob_name)

    content_settings = ContentSettings(content_type="model/vnd.usdz+zip")
    with open(local_path, "rb") as f:
        blob_client.upload_blob(f, overwrite=True, content_settings=content_settings)

    url = f"{settings.cdn_base_url.rstrip('/')}/{blob_name}"
    logger.debug(f"Uploaded USDZ to {url}")
    return url
