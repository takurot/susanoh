import os
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from passlib.context import CryptContext

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "susanoh-secret-key-dev-only-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 day

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

class User(BaseModel):
    username: str
    role: Role

# Mock Database
# Passwords are: "password123"
MOCK_USERS_DB = {
    "admin": {
        "username": "admin",
        "hashed_password": pwd_context.hash("password123"),
        "role": Role.ADMIN,
    },
    "operator": {
        "username": "operator",
        "hashed_password": pwd_context.hash("password123"),
        "role": Role.OPERATOR,
    },
    "viewer": {
        "username": "viewer",
        "hashed_password": pwd_context.hash("password123"),
        "role": Role.VIEWER,
    },
}

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_user(db: dict, username: str) -> Optional[dict]:
    if username in db:
        user_dict = db[username]
        return user_dict
    return None

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role_str: str = payload.get("role")
        if username is None or role_str is None:
            raise credentials_exception
        role = Role(role_str)
    except jwt.PyJWTError:
        raise credentials_exception
    
    user_dict = get_user(MOCK_USERS_DB, username)
    if user_dict is None:
        raise credentials_exception
    return User(username=username, role=role)

def require_roles(allowed_roles: list[Role]):
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Requires one of: {[r.value for r in allowed_roles]}",
            )
        return current_user
    return role_checker
