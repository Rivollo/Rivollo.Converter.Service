import logging
import os
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

USDZ_ASSET_ID = 11


def save_usdz_asset(
    db: Session,
    blob_url: str,
    local_path: str,
    product_id: str,
    user_id: str,
    name: str,
) -> None:
    size_bytes = os.path.getsize(local_path) if os.path.exists(local_path) else 0
    now = datetime.now(timezone.utc)

    result = db.execute(text("""
        INSERT INTO public.tbl_product_assets
            (asset_id, image, size_bytes, created_by, created_date)
        VALUES (:asset_id, :image, :size_bytes, :created_by, :created_date)
        RETURNING id
    """), {"asset_id": USDZ_ASSET_ID, "image": blob_url, "size_bytes": size_bytes,
           "created_by": user_id, "created_date": now})
    db.commit()
    product_asset_id = str(result.fetchone()[0])

    db.execute(text("""
        INSERT INTO public.tbl_product_asset_mapping
            (name, productid, product_asset_id, isactive, created_by, created_date)
        VALUES (:name, :productid, :product_asset_id, true, :created_by, :created_date)
    """), {"name": f"{name}_usdz", "productid": product_id,
           "product_asset_id": product_asset_id, "created_by": user_id, "created_date": now})
    db.commit()
    logger.info(f"[DB] USDZ asset saved: product={product_id} url={blob_url}")


def update_product_status(db: Session, product_id: str, status: str) -> None:
    db.execute(text("""
        UPDATE public.tbl_products
        SET status = :status, updated_date = :now
        WHERE id = :product_id
    """), {"status": status, "now": datetime.now(timezone.utc), "product_id": product_id})
    db.commit()
    logger.info(f"[DB] Product {product_id} status → {status}")
