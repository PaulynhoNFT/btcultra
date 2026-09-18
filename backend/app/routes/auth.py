from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr
from app.auth import (
    authenticate_user, create_access_token, create_refresh_token,
    decode_token, decode_refresh_token, verify_refresh_token_db,
    revoke_refresh_token, create_refresh_token_db, get_user_by_id,
    generate_totp_secret, get_totp_uri, generate_qr_code,
    generate_backup_codes, enable_totp, disable_totp, verify_totp,
    hash_backup_code,
)
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


# ============================================================
# Schemas
# ============================================================
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class TOTPSetupResponse(BaseModel):
    secret: str
    qr_code: str
    backup_codes: list[str]


class TOTPVerifyRequest(BaseModel):
    code: str


class TOTPDisableRequest(BaseModel):
    password: str
    totp_code: Optional[str] = None
    backup_code: Optional[str] = None


# ============================================================
# Dependency: current user
# ============================================================
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token_data = decode_token(credentials.credentials)
    user = await get_user_by_id(db, token_data.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


# ============================================================
# Routes
# ============================================================
@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await get_user_by_id(db, UUID(int=0))  # dummy, will use email
    # Check email exists
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.email == request.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = await create_user(db, request.email, request.password)
    access = create_access_token({"sub": str(user.id), "email": user.email})
    refresh = create_refresh_token({"sub": str(user.id), "email": user.email})
    await create_refresh_token_db(db, user.id, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, request.email, request.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Check 2FA
    if user.totp_enabled:
        if not request.totp_code:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="2FA required")
        if not verify_totp(user.totp_secret, request.totp_code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code")

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    access = create_access_token({"sub": str(user.id), "email": user.email})
    refresh = create_refresh_token({"sub": str(user.id), "email": user.email})
    await create_refresh_token_db(db, user.id, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    rt = await verify_refresh_token_db(db, request.refresh_token)
    if not rt:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    # Rotate: revoke old, issue new
    await revoke_refresh_token(db, request.refresh_token)
    new_access = create_access_token({"sub": str(rt.user_id), "email": rt.user.email})
    new_refresh = create_refresh_token({"sub": str(rt.user_id), "email": rt.user.email})
    await create_refresh_token_db(db, rt.user_id, new_refresh)
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout")
async def logout(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    await revoke_refresh_token(db, request.refresh_token)
    return {"message": "Logged out"}


@router.get("/me", response_model=dict)
async def me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "plan": current_user.plan,
        "totp_enabled": current_user.totp_enabled,
        "quota_daily": current_user.quota_daily,
        "quota_monthly": current_user.quota_monthly,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at.isoformat(),
    }


# ============================================================
# 2FA
# ============================================================
@router.post("/2fa/setup", response_model=TOTPSetupResponse)
async def setup_2fa(current_user: User = Depends(get_current_user)):
    if current_user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA already enabled")

    secret = generate_totp_secret()
    uri = get_totp_uri(secret, current_user.email)
    qr_code = generate_qr_code(uri)
    backup_codes = generate_backup_codes()

    # Store temporarily (in production, use a pending table)
    # For now, return to user - they must verify to enable
    return TOTPSetupResponse(secret=secret, qr_code=qr_code, backup_codes=backup_codes)


@router.post("/2fa/enable")
async def enable_2fa(request: TOTPVerifyRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA already enabled")

    # The secret was returned in setup - user should have saved it
    # In production, store secret temporarily during setup flow
    # For now, require user to provide secret again (not ideal but works)
    # Better: store in user.totp_secret_pending during setup
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Complete 2FA flow requires pending secret storage")


@router.post("/2fa/verify-enable")
async def verify_enable_2fa(
    secret: str,
    code: str,
    backup_codes: list[str],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA already enabled")

    if not verify_totp(secret, code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid 2FA code")

    hashed_backups = [hash_backup_code(c) for c in backup_codes]
    # In production, store hashed backups in separate table
    await enable_totp(db, current_user.id, secret, backup_codes)
    return {"message": "2FA enabled"}


@router.post("/2fa/disable")
async def disable_2fa(request: TOTPDisableRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not current_user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA not enabled")

    # Verify password
    from app.auth import verify_password
    if not verify_password(request.password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    # Verify 2FA or backup code
    verified = False
    if request.totp_code and verify_totp(current_user.totp_secret, request.totp_code):
        verified = True
    elif request.backup_code:
        # Check against stored hashed backup codes
        pass  # Implement backup code verification

    if not verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code or backup code")

    await disable_totp(db, current_user.id)
    return {"message": "2FA disabled"}
