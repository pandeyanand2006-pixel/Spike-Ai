"""Authentication endpoints."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings
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

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _google_redirect_uri(request: Request) -> str:
    """Build the exact redirect URI Google expects.

    Behind proxies (Render) request.base_url can come back as http://, which
    would not match the https:// URI registered in Google Cloud. Always use
    https:// + the Host header (or an explicit GOOGLE_REDIRECT_URI env var).
    """
    settings = get_settings()
    if getattr(settings, "google_redirect_uri", None):
        return settings.google_redirect_uri
    host = request.headers.get("host", "spike-ai.onrender.com")
    return f"https://{host}/api/auth/google/callback"


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
    settings = get_settings()
    return {
        "enabled": True,
        "database": "connected" if await ping() else "unavailable",
        "google": bool(settings.google_client_id and settings.google_client_secret),
        "image": bool(settings.image_gen_api_key),
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


@router.post("/forgot-password")
async def forgot_password(req: dict):
    """Password reset request.

    NOTE: email-sending requires SMTP configuration (SMTP_HOST/SMTP_USER/
    SMTP_PASS) which is not wired yet. Until then we return a clear,
    honest message instead of faking a reset email.
    """
    settings = get_settings()
    if not getattr(settings, "smtp_host", None):
        return {
            "configured": False,
            "message": (
                "Password reset email is not configured on the server yet. "
                "Please contact support or set SMTP credentials."
            ),
        }
    return {"configured": True, "message": "If the email exists, a reset link was sent."}


# ---------- Google OAuth (config-gated) ----------

@router.get("/google")
async def google_login(request: Request):
    """Begin Google OAuth. Redirects to Google if configured, else 503."""
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google login is not configured.",
        )
    redirect_uri = _google_redirect_uri(request)
    params = (
        f"client_id={settings.google_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
    )
    return {"url": f"{GOOGLE_AUTH_URL}?{params}"}


@router.get("/google/callback")
async def google_callback(request: Request, code: str = ""):
    """Handle Google OAuth callback, create/find user, return token."""
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google login is not configured.",
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code.",
        )
    redirect_uri = _google_redirect_uri(request)
    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code != 200:
                raise Exception(
                    f"token endpoint {token_resp.status_code}: {token_resp.text[:300]}"
                )
            access = token_resp.json().get("access_token")
            user_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access}"},
            )
            if user_resp.status_code != 200:
                raise Exception(
                    f"userinfo {user_resp.status_code}: {user_resp.text[:300]}"
                )
            info = user_resp.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google authentication failed: {e}",
        )

    email = (info.get("email") or "").lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google did not provide an email.",
        )
    user = await user_model.find_by_email(email)
    if user is None:
        name = info.get("name") or email.split("@")[0]
        user = await user_model.create_user(
            name, email, hash_password(_random_secret())
        )
    token = create_access_token(user["id"])
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/#gtoken=" + token)


def _random_secret() -> str:
    import secrets

    return secrets.token_urlsafe(24)
