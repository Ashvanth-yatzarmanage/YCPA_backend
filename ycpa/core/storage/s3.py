import asyncio
import logging
from typing import Any, Dict, List, Optional, Set  # noqa: UP035
from uuid import uuid4

import aioboto3
from botocore.exceptions import ClientError
from fastapi import HTTPException, UploadFile

from ycpa.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


S3_BUCKET: str = settings.S3_BUCKET_NAME
S3_REGION: str = settings.AWS_REGION
MAX_FILE_SIZE: int = settings.S3_MAX_FILE_SIZE


ALLOWED_EXTENSIONS: set[str] = {
    # BIM / CAD
    "ifc", "frag",
    "dwg", "dxf",
    "rvt", "rfa", "rte", "rft",
    "nwd", "nwc", "nwf",
    "pln", "mod", "gsm", "tpl", "ach",
    "3dm",
    "skp",
    "sat", "sab",
    "stp", "step",
    "igs", "iges",
    "3ds",
    "dgn",
    "prt", "asm", "sldprt", "sldasm",
    "x_t", "x_b",
    "brep",
    # Point Clouds
    "e57", "las", "laz", "pts", "xyz",
    "pcd", "ply", "ptx", "rcp", "rcs",
    # BIM Collaboration
    "bcf", "bcfzip",
    # GIS
    "shp", "shx", "dbf", "prj",
    "geojson", "kml", "kmz", "gpx",
    # Documents
    "pdf",
    "docx", "doc", "odt", "rtf", "txt", "md",
    # Spreadsheets
    "xlsx", "xls", "ods", "csv", "tsv",
    # Presentations
    "pptx", "ppt", "odp",
    # Images
    "jpg", "jpeg", "png", "webp",
    "gif", "bmp", "svg",
    "tif", "tiff",
    # Video
    "mp4", "mov", "avi", "mkv", "webm", "wmv",
    # 3D / Rendering
    "gltf", "glb",
    "obj", "mtl",
    "fbx",
    "stl", "3mf",
    "usd", "usda", "usdc", "usdz",
    "dae",
    "abc",
    # Data / Config
    "json", "xml",
    "yaml", "yml",
    "html", "htm",
    # Archives
    "zip", "rar", "7z", "tar", "gz", "bz2",
}

CONTENT_TYPE_MAP: dict[str, str] = {
    # BIM
    "ifc":    "application/x-step",
    "frag":   "application/octet-stream",
    "dwg":    "application/acad",
    "dxf":    "image/vnd.dxf",
    "rvt":    "application/octet-stream",
    "rfa":    "application/octet-stream",
    "nwd":    "application/octet-stream",
    "skp":    "application/octet-stream",
    "3dm":    "application/octet-stream",
    "stp":    "application/step",
    "step":   "application/step",
    "igs":    "model/iges",
    "iges":   "model/iges",
    "dgn":    "application/octet-stream",
    # BCF
    "bcf":    "application/octet-stream",
    "bcfzip": "application/zip",
    # Point clouds
    "e57":    "application/octet-stream",
    "las":    "application/octet-stream",
    "laz":    "application/octet-stream",
    "ply":    "application/octet-stream",
    # GIS
    "geojson": "application/geo+json",
    "kml":    "application/vnd.google-earth.kml+xml",
    "kmz":    "application/vnd.google-earth.kmz",
    "shp":    "application/octet-stream",
    # Documents
    "pdf":    "application/pdf",
    "docx":   "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc":    "application/msword",
    "odt":    "application/vnd.oasis.opendocument.text",
    "rtf":    "application/rtf",
    "txt":    "text/plain",
    "md":     "text/markdown",
    # Spreadsheets
    "xlsx":   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls":    "application/vnd.ms-excel",
    "ods":    "application/vnd.oasis.opendocument.spreadsheet",
    "csv":    "text/csv",
    "tsv":    "text/tab-separated-values",
    # Presentations
    "pptx":   "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt":    "application/vnd.ms-powerpoint",
    "odp":    "application/vnd.oasis.opendocument.presentation",
    # Images
    "jpg":    "image/jpeg",
    "jpeg":   "image/jpeg",
    "png":    "image/png",
    "webp":   "image/webp",
    "gif":    "image/gif",
    "bmp":    "image/bmp",
    "svg":    "image/svg+xml",
    "tif":    "image/tiff",
    "tiff":   "image/tiff",
    # Video
    "mp4":    "video/mp4",
    "mov":    "video/quicktime",
    "avi":    "video/x-msvideo",
    "mkv":    "video/x-matroska",
    "webm":   "video/webm",
    "wmv":    "video/x-ms-wmv",
    # 3D
    "gltf":   "model/gltf+json",
    "glb":    "model/gltf-binary",
    "obj":    "text/plain",
    "fbx":    "application/octet-stream",
    "stl":    "model/stl",
    "3mf":    "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
    "usd":    "model/vnd.usdz+zip",
    "usdz":   "model/vnd.usdz+zip",
    "dae":    "model/vnd.collada+xml",
    # Data
    "json":   "application/json",
    "xml":    "application/xml",
    "yaml":   "application/yaml",
    "yml":    "application/yaml",
    "html":   "text/html",
    "htm":    "text/html",
    # Archives
    "zip":    "application/zip",
    "rar":    "application/vnd.rar",
    "7z":     "application/x-7z-compressed",
    "tar":    "application/x-tar",
    "gz":     "application/gzip",
    "bz2":    "application/x-bzip2",
}


def _get_secret(value: Any) -> str:
    return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)


_session = aioboto3.Session(
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=_get_secret(settings.AWS_SECRET_ACCESS_KEY),
    region_name=S3_REGION,
)


def get_content_type(extension: str, fallback: str = "application/octet-stream") -> str:
    return CONTENT_TYPE_MAP.get(extension.lower().lstrip("."), fallback)



async def upload_file_to_s3(
    file: UploadFile,
    folder: str = "uploads",
    max_size: int | None = None,
    upload_id: str | None = None,
) -> dict[str, Any]:

    upload_id = upload_id or str(uuid4())
    max_size  = max_size or MAX_FILE_SIZE

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    parts     = file.filename.rsplit(".", 1)
    extension = parts[1].lower() if len(parts) == 2 else ""
    key       = f"{folder}/{upload_id}.{extension}" if extension else f"{folder}/{upload_id}"
    content_type = get_content_type(extension, file.content_type or "application/octet-stream")

    data = await file.read()
    size = len(data)

    if size > max_size:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large — max {max_size / (1024 * 1024):.0f} MB, "
                f"yours is {size / (1024 * 1024):.1f} MB"
            ),
        )

    async with _session.client("s3") as s3:
        await s3.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
            Metadata={
                "original-filename": file.filename,
                "file-size":         str(size),
                "upload-id":         upload_id,
            },
        )

    logger.info("S3 upload OK", extra={"key": key, "size": size})
    return {
        "url":               f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{key}",
        "key":               key,
        "bucket":            S3_BUCKET,
        "size":              size,
        "content_type":      content_type,
        "original_filename": file.filename,
        "upload_id":         upload_id,
    }


async def delete_file_from_s3(key: str) -> bool:
    try:
        async with _session.client("s3") as s3:
            await s3.delete_object(Bucket=S3_BUCKET, Key=key)
        logger.info("S3 delete OK", extra={"key": key})
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        raise HTTPException(status_code=500, detail=f"S3 delete failed: {code}")


async def generate_presigned_url(key: str, expiration: int = 3600) -> str:
    try:
        async with _session.client("s3") as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET, "Key": key},
                ExpiresIn=expiration,
            )
        return url
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        raise HTTPException(status_code=500, detail=f"Failed to generate presigned URL: {code}")


async def get_file_size(key: str) -> int | None:
    try:
        async with _session.client("s3") as s3:
            head = await s3.head_object(Bucket=S3_BUCKET, Key=key)
        return head["ContentLength"]
    except ClientError:
        return None


async def get_object_bytes(key: str) -> tuple[bytes, str]:
    try:
        async with _session.client("s3") as s3:
            resp         = await s3.get_object(Bucket=S3_BUCKET, Key=key)
            content      = await resp["Body"].read()
            content_type = resp.get("ContentType", "application/octet-stream")
        return content, content_type
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        raise HTTPException(status_code=500, detail=f"S3 fetch failed: {code}")


async def list_files_from_s3(
    folder: str = "uploads",
    file_extension: str | None = None,
) -> list[dict[str, Any]]:

    prefix = folder if folder.endswith("/") else f"{folder}/"

    async with _session.client("s3") as s3:

        resp        = await s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        raw_objects = resp.get("Contents", [])

        if file_extension:
            norm_ext    = f".{file_extension.lower().lstrip('.')}"
            raw_objects = [
                o for o in raw_objects
                if not o["Key"].endswith("/") and o["Key"].lower().endswith(norm_ext)
            ]
        else:
            raw_objects = [o for o in raw_objects if not o["Key"].endswith("/")]

        if not raw_objects:
            return []

        async def _enrich(obj: dict) -> dict[str, Any] | None:
            key = obj["Key"]
            try:
                head     = await s3.head_object(Bucket=S3_BUCKET, Key=key)
                metadata = head.get("Metadata", {})
                filename = metadata.get("original-filename", key.split("/")[-1])
                url      = await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": S3_BUCKET, "Key": key},
                    ExpiresIn=3600,
                )
            except ClientError as e:
                logger.warning(
                    "Skipping S3 object — enrich failed",
                    extra={"key": key, "error": str(e)},
                )
                return None

            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            return {
                "key":           key,
                "filename":      filename,
                "size":          obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
                "url":           url,
                "content_type":  get_content_type(ext),
            }

        results = await asyncio.gather(*[_enrich(o) for o in raw_objects])

    files = sorted(
        [r for r in results if r is not None],
        key=lambda x: x["last_modified"],
        reverse=True,
    )

    logger.info("S3 list OK", extra={"folder": folder, "count": len(files)})
    return files


__all__ = [
    "S3_BUCKET",
    "S3_REGION",
    "ALLOWED_EXTENSIONS",
    "CONTENT_TYPE_MAP",
    "get_content_type",
    "upload_file_to_s3",
    "delete_file_from_s3",
    "generate_presigned_url",
    "get_file_size",
    "get_object_bytes",
    "list_files_from_s3",
]
