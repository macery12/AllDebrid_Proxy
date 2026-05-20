import redis
from datetime import timezone
from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.schemas import LoginRequest, LoginResponse, UserOut
from app.auth.jwt import create_access_token, set_auth_cookie, clear_auth_cookie, decode_access_token, COOKIE_NAME
from app.auth.deps import get_current_user
from app.services import user_service
from app.config import settings
import jwt

router = APIRouter(tags=["auth"])

_r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db)):
    return {"first_time_setup": not user_service.has_users(db)}


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    # First-time setup: no users exist yet
    if not user_service.has_users(db):
        user_service.create_first_admin(db, body.username, body.password)
        return LoginResponse(
            first_time_setup=True,
            message="Admin account created. Please log in with your new credentials.",
        )

    user = user_service.authenticate(db, body.username, body.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(user, remember_me=body.remember_me)
    set_auth_cookie(response, token, remember_me=body.remember_me)
    return LoginResponse(user=UserOut(id=user.id, username=user.username, is_admin=user.is_admin, role=user.role))


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        try:
            payload = decode_access_token(token)
            jti = payload.get("jti")
            if jti:
                exp = payload.get("exp", 0)
                # TTL = remaining seconds on the token, min 60s
                import time
                ttl = max(int(exp - time.time()), 60)
                _r.setex(f"jwt_block:{jti}", ttl, "1")
        except jwt.InvalidTokenError:
            pass
    clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(get_current_user)):
    return UserOut(id=user.id, username=user.username, is_admin=user.is_admin, role=user.role)
