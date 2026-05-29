from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from auth.db import get_user
from auth.service import verify_password, create_access_token, JWT_SECRET, JWT_ALGORITHM
from jose import jwt, JWTError

router = APIRouter()

class LoginRequest(BaseModel):
    operatorId: str
    password: str

class LoginResponse(BaseModel):
    token: str
    role: str
    expiresIn: int

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    user = await get_user(request.operatorId)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not user["active"]:
        raise HTTPException(status_code=401, detail="Account is inactive")
    
    if not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_access_token(user["operator_id"], user["role"])
    return LoginResponse(
        token=token,
        role=user["role"],
        expiresIn=28800 # 8 hours
    )

@router.get("/verify")
async def verify(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token")
    
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            "operatorId": payload["sub"],
            "role": payload["role"]
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
