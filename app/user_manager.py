"""User management utilities for database-backed authentication"""
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash
from app.models import User, UserStats
from app.db import SessionLocal
from datetime import datetime
from typing import Optional

def create_user(username: str, password: str, is_admin: bool = False) -> User:
    """Create a new user with hashed password"""
    with SessionLocal() as session:
        # Check if user already exists
        existing = session.query(User).filter(User.username == username).first()
        if existing:
            raise ValueError(f"User '{username}' already exists")
        
        # Create user
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            is_admin=is_admin
        )
        session.add(user)
        session.flush()
        
        # Create stats for user
        stats = UserStats(user_id=user.id)
        session.add(stats)
        
        session.commit()
        session.refresh(user)
        return user

def verify_user(username: str, password: str) -> Optional[User]:
    """Verify user credentials and return user if valid"""
    with SessionLocal() as session:
        user = session.query(User).filter(User.username == username).first()
        if user and check_password_hash(user.password_hash, password):
            # Update last login
            user.last_login = datetime.utcnow()
            session.commit()
            # Access all attributes to load them before expunging
            _ = (user.id, user.username, user.password_hash, user.is_admin, 
                 user.created_at, user.last_login)
            session.expunge(user)
            return user
        return None

def get_user_by_username(username: str) -> Optional[User]:
    """Get user by username"""
    with SessionLocal() as session:
        user = session.query(User).filter(User.username == username).first()
        if user:
            # Access all attributes to load them before expunging
            _ = (user.id, user.username, user.password_hash, user.is_admin, 
                 user.created_at, user.last_login)
            session.expunge(user)
        return user

def get_user_by_id(user_id: int) -> Optional[User]:
    """Get user by ID"""
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user:
            # Access all attributes to load them before expunging
            _ = (user.id, user.username, user.password_hash, user.is_admin, 
                 user.created_at, user.last_login)
            session.expunge(user)
        return user

def has_any_users() -> bool:
    """Check if any users exist in the database"""
    with SessionLocal() as session:
        count = session.query(User).count()
        return count > 0

def update_user_stats(user_id: int, increment_downloads: int = 0, 
                      increment_magnets: int = 0, add_bytes: int = 0):
    """Update user statistics"""
    with SessionLocal() as session:
        stats = session.query(UserStats).filter(UserStats.user_id == user_id).first()
        if stats:
            stats.total_downloads += increment_downloads
            stats.total_magnets_processed += increment_magnets
            stats.total_bytes_downloaded += add_bytes
            stats.updated_at = datetime.utcnow()
            session.commit()

def get_all_users() -> list[User]:
    """Get all users"""
    with SessionLocal() as session:
        users = session.query(User).all()
        for user in users:
            # Access all attributes to load them before expunging
            _ = (user.id, user.username, user.password_hash, user.is_admin, 
                 user.created_at, user.last_login)
            # Also load stats relationship if it exists
            if hasattr(user, 'stats') and user.stats:
                _ = (user.stats.total_downloads, user.stats.total_magnets_processed, 
                     user.stats.total_bytes_downloaded)
            session.expunge(user)
        return users

def update_user_password(user_id: int, new_password: str):
    """Update user password"""
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user:
            user.password_hash = generate_password_hash(new_password)
            session.commit()

def delete_user(user_id: int):
    """Delete a user"""
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user:
            session.delete(user)
            session.commit()

def toggle_admin(user_id: int) -> bool:
    """Toggle admin status and return new status"""
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user:
            user.is_admin = not user.is_admin
            session.commit()
            return user.is_admin
        return False
