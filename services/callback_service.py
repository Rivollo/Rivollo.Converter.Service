import logging

import httpx

logger = logging.getLogger(__name__)


async def post_callback(callback_url: str, payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(callback_url, json=payload)
            response.raise_for_status()
        logger.info(f"Callback posted to {callback_url}, status={response.status_code}")
    except Exception as exc:
        logger.error(f"Callback to {callback_url} failed: {exc}")
