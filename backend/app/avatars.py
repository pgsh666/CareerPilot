"""Confirmed profile uploads; canonical raster only, one private image per account."""
import base64
import secrets
import warnings
from io import BytesIO

from fastapi import APIRouter, Request, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, select
from starlette.concurrency import run_in_threadpool

from app.auth import Current, Db, Protected, user_payload
from app.errors import ApiError
from app.models import AvatarImage
from app.training_service import lock_owner

router = APIRouter(prefix="/api/v1/account/avatar", tags=["accounts"])
MAX_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 16_000_000


def normalize_image(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ApiError(422, "AVATAR_FORMAT", "请选择JPG、PNG或WebP静态图片")
                if source.width * source.height > MAX_PIXELS or max(source.size) > 10000:
                    raise ApiError(422, "AVATAR_DIMENSIONS", "图片尺寸过大，请缩小后重试")
                if getattr(source, "n_frames", 1) != 1:
                    raise ApiError(422, "AVATAR_ANIMATED", "请选择静态图片作为头像")
                source.load()
                upright = ImageOps.exif_transpose(source)
                fitted = ImageOps.fit(upright.convert("RGBA"), (256, 256), method=Image.Resampling.LANCZOS)
                # A new raster strips EXIF/location/text chunks and ignores appended payloads.
                clean = Image.new("RGBA", (256, 256))
                clean.paste(fitted)
                output = BytesIO()
                clean.save(output, format="PNG")
                return base64.b64encode(output.getvalue()).decode("ascii")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ApiError(422, "AVATAR_INVALID", "图片无法读取，请重新选择有效的JPG、PNG或WebP图片") from None


@router.put("")
async def upload(request: Request, db: Db, context: Protected):
    if context.user.role == "admin":
        raise ApiError(403, "PROFILE_NOT_AVAILABLE", "管理员使用固定头像")
    data = bytearray()
    async for part in request.stream():
        if len(data) + len(part) > MAX_BYTES:
            raise ApiError(413, "AVATAR_TOO_LARGE", "头像图片不能超过2MB")
        data.extend(part)
    if not data:
        raise ApiError(422, "AVATAR_EMPTY", "请选择头像图片")
    encoded = await run_in_threadpool(normalize_image, bytes(data))
    user = lock_owner(db, context.user.id)
    identifier = "upload_" + secrets.token_urlsafe(12)
    db.execute(delete(AvatarImage).where(AvatarImage.owner_id == user.id))
    db.add(AvatarImage(id=identifier, owner_id=user.id, png_base64=encoded))
    user.avatar = identifier
    db.commit()
    return {"account": user_payload(user)}


@router.get("/{avatar_id}")
def read(avatar_id: str, db: Db, context: Current):
    image = db.scalar(select(AvatarImage).where(AvatarImage.id == avatar_id, AvatarImage.owner_id == context.user.id))
    if not image or context.user.avatar != avatar_id:
        raise ApiError(404, "AVATAR_NOT_FOUND", "头像不存在或不可访问")
    return Response(base64.b64decode(image.png_base64), media_type="image/png")
