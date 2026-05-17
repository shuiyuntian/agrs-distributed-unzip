"""
用户管理 API
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from master.api.auth import get_current_user, get_password_hash
from master.database import get_all_users, create_user, delete_user, get_user_by_username

router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    username: str
    password: str


@router.get("/list")
async def list_users(current_user: dict = Depends(get_current_user)):
    """获取所有用户"""
    users = await get_all_users()
    return {"users": users}


@router.post("/create")
async def create_new_user(payload: UserCreate, current_user: dict = Depends(get_current_user)):
    """创建新用户"""
    existing = await get_user_by_username(payload.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    hashed = get_password_hash(payload.password)
    user_id = await create_user(payload.username, hashed)
    return {"success": True, "id": user_id}


@router.delete("/{user_id}")
async def remove_user(user_id: int, current_user: dict = Depends(get_current_user)):
    """删除用户（不能删除自己）"""
    if current_user["id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    await delete_user(user_id)
    return {"success": True}
