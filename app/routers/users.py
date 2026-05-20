from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.auth.deps import require_admin
from app.schemas import CreateUserRequest, ResetPasswordRequest, SetRoleRequest
from app.services import user_service

router = APIRouter(tags=["users"])


@router.get("")
def list_users(user=Depends(require_admin), db: Session = Depends(get_db)):
    return user_service.list_users(db)


@router.post("", status_code=201)
def create_user(
    req: CreateUserRequest,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    role = req.role or ("admin" if req.is_admin else "user")
    return user_service.create_user(db, req.username, req.password, role)


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    return user_service.delete_user(db, user_id, user.id)


@router.post("/{user_id}/role")
def set_role(
    user_id: int,
    req: SetRoleRequest,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    return user_service.set_role(db, user_id, req.role)


@router.post("/{user_id}/toggle-admin")
def toggle_admin(
    user_id: int,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    return user_service.toggle_admin(db, user_id)


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    req: ResetPasswordRequest,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    return user_service.reset_password(db, user_id, req.password)
