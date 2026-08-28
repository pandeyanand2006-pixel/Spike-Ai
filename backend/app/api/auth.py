"""Authentication endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.middleware.auth import get_current_user
from app.models import user as user_model
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    UserOut,
)
from app.utils.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.db import ping

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: dict) -> UserOut:
    return UserOut(
        id=user["id"],
        name=user.get("name", ""),
        email=user.get("email", ""),
        createdAt=user.get("createdAt"),
    )


@router.get("/status")
async def auth_status():
    """Report whether the authentication/database system is available."""
    return {
        "enabled": True,
        "database": "connected" if await ping() else "unavailable",
    }


@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest):
    existing = await user_model.find_by_email(req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    user = await user_model.create_user(
        req.name.strip(), req.email, hash_password(req.password)
    )
    token = create_access_token(user["id"])
    return AuthResponse(
        access_token=token,
        user=_user_out(user),
    )


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    user = await user_model.find_by_email(req.email)
    if user is None or not verify_password(req.password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    token = create_access_token(user["id"])
    return AuthResponse(
        access_token=token,
        user=_user_out(user),
    )


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
):
    if not verify_password(req.current_password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    await user_model.update_password(user["id"], hash_password(req.new_password))
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)):
    return _user_out(user)
