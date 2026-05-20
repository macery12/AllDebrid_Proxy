from sqlalchemy.orm import Session
from sqlalchemy import select
from fastapi import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from app.models import User, UserStats, VALID_ROLES, ROLE_ADMIN, ROLE_USER


def _user_to_dict(u: User, stats: UserStats | None = None) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "is_admin": u.is_admin,
        "role": u.role,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "stats": {
            "total_magnets_processed": stats.total_magnets_processed,
            "total_downloads": stats.total_downloads,
            "total_bytes_downloaded": stats.total_bytes_downloaded,
        } if stats else None,
    }


def has_users(db: Session) -> bool:
    return db.execute(select(User)).first() is not None


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if not user or not check_password_hash(user.password_hash, password):
        return None
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    return user


def create_first_admin(db: Session, username: str, password: str) -> User:
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        is_admin=True,
        role=ROLE_ADMIN,
    )
    db.add(user)
    db.flush()
    db.add(UserStats(user_id=user.id))
    db.commit()
    return user


def create_user(db: Session, username: str, password: str, role: str) -> dict:
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role '{role}'")
    if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"User '{username}' already exists")
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        is_admin=(role == ROLE_ADMIN),
        role=role,
    )
    db.add(user)
    db.flush()
    db.add(UserStats(user_id=user.id))
    db.commit()
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin, "role": user.role}


def list_users(db: Session) -> dict:
    users = db.execute(select(User).order_by(User.created_at.asc())).scalars().all()
    result = []
    for u in users:
        stats = db.execute(select(UserStats).where(UserStats.user_id == u.id)).scalar_one_or_none()
        result.append(_user_to_dict(u, stats))
    return {"users": result}


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def delete_user(db: Session, user_id: int, requesting_user_id: int) -> dict:
    if user_id == requesting_user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    user = db.get(User, user_id)
    if user:
        db.delete(user)
        db.commit()
    return {"ok": True}


def set_role(db: Session, user_id: int, role: str) -> dict:
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role '{role}'")
    user = get_user(db, user_id)
    user.role = role
    user.is_admin = (role == ROLE_ADMIN)
    db.commit()
    return {"is_admin": user.is_admin, "role": user.role}


def toggle_admin(db: Session, user_id: int) -> dict:
    user = get_user(db, user_id)
    user.is_admin = not user.is_admin
    user.role = ROLE_ADMIN if user.is_admin else ROLE_USER
    db.commit()
    return {"is_admin": user.is_admin, "role": user.role}


def reset_password(db: Session, user_id: int, new_password: str) -> dict:
    user = get_user(db, user_id)
    user.password_hash = generate_password_hash(new_password)
    db.commit()
    return {"ok": True}
