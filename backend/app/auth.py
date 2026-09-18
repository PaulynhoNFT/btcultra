from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4
import hashlib
import secrets
import pyotp
import qrcode
import io
import base64
from passlib.context import CryptContext
from jose import jwt, JWTError
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from app.config import get_settings
from app.models import User, RefreshToken
from app.database import get_db

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ============================================================
# Schemas
# ============================================================
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[UUID] = None
    email: Optional[str] = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = None


class UserResponse(BaseModel):
    id: UUID
    email: str
    plan: str
    totp_enabled: bool
    quota_daily: int
    quota_monthly: int
    is_active: bool
    created_at: datetime


class TOTPSetup(BaseModel):
    secret: str
    qr_code: str  # base64 PNG
    backup_codes: list[str]


# ============================================================
# Password hashing
# ============================================================
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ============================================================
# JWT
# ============================================================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(days=settings.refresh_token_expire_days))
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            raise JWTError("Invalid token type")
        user_id = payload.get("sub")
        email = payload.get("email")
        if user_id is None:
            raise JWTError("Missing subject")
        return TokenData(user_id=UUID(user_id), email=email)
    except JWTError as e:
        raise JWTError(f"Invalid token: {e}")


def decode_refresh_token(token: str) -> UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "refresh":
            raise JWTError("Invalid token type")
        user_id = payload.get("sub")
        if user_id is None:
            raise JWTError("Missing subject")
        return UUID(user_id)
    except JWTError as e:
        raise JWTError(f"Invalid refresh token: {e}")


# ============================================================
# TOTP (2FA)
# ============================================================
def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.totp_issuer)


def generate_qr_code(uri: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=valid_window)


def generate_backup_codes(count: int = 8) -> list[str]:
    return [secrets.token_hex(4).upper() for _ in range(count)]


def hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


# ============================================================
# User CRUD
# ============================================================
async def create_user(db: AsyncSession, email: str, password: str) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        totp_secret=None,
        totp_enabled=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, email: str, password: str) -> Optional[User]:
    user = await get_user_by_email(db, email)
    if not user or not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


# ============================================================
# Refresh tokens (rotating)
# ============================================================
async def create_refresh_token_db(db: AsyncSession, user_id: UUID, token: str) -> RefreshToken:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    rt = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(rt)
    await db.commit()
    await db.refresh(rt)
    return rt


async def verify_refresh_token_db(db: AsyncSession, token: str) -> Optional[RefreshToken]:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .where(RefreshToken.revoked_at.is_(None))
        .where(RefreshToken.expires_at > datetime.now(timezone.utc))
        .options(selectinload(RefreshToken.user))
    )
    return result.scalar_one_or_none()


async def revoke_refresh_token(db: AsyncSession, token: str) -> bool:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()
    if rt:
        rt.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        return True
    return False


async def revoke_all_user_tokens(db: AsyncSession, user_id: UUID) -> int:
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id).where(RefreshToken.revoked_at.is_(None))
    )
    tokens = result.scalars().all()
    for rt in tokens:
        rt.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return len(tokens)


async def cleanup_expired_tokens(db: AsyncSession) -> int:
    result = await db.execute(
        delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(timezone.utc))
    )
    return result.rowcount


# ============================================================
# TOTP management
# ============================================================
async def enable_totp(db: AsyncSession, user_id: UUID, secret: str, backup_codes: list[str]) -> User:
    user = await get_user_by_id(db, user_id)
    if not user:
        raise ValueError("User not found")
    user.totp_secret = secret
    user.totp_enabled = True
    # Store hashed backup codes (in production, add a separate table)
    await db.commit()
    await db.refresh(user)
    return user


async def disable_totp(db: AsyncSession, user_id: UUID) -> User:
    user = await get_user_by_id(db, user_id)
    if not user:
        raise ValueError("User not found")
    user.totp_secret = None
    user.totp_enabled = False
    await db.commit()
    await db.refresh(user)
    return user
