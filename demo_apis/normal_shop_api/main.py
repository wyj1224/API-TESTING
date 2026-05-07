from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: int
    email: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ItemCreate(BaseModel):
    name: str = Field(min_length=1)
    price: float = Field(gt=0)


class ItemResponse(BaseModel):
    id: int
    name: str
    price: float


security = HTTPBearer(auto_error=False)
app = FastAPI(title="Normal Shop API")

users: dict[str, dict[str, str | int]] = {}
tokens: dict[str, str] = {}
items: dict[int, ItemResponse] = {}
next_user_id = 1
next_item_id = 1


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> dict[str, str | int]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email = tokens.get(credentials.credentials)
    if email is None or email not in users:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return users[email]


@app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> UserResponse:
    global next_user_id

    if payload.email in users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    user = {"id": next_user_id, "email": payload.email, "password": payload.password}
    users[payload.email] = user
    next_user_id += 1
    return UserResponse(id=int(user["id"]), email=str(user["email"]))


@app.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    user = users.get(payload.email)
    if user is None or user["password"] != payload.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = f"normal-token-{payload.email}"
    tokens[token] = payload.email
    return TokenResponse(access_token=token)


@app.get("/users/me", response_model=UserResponse)
def read_current_user(
    current_user: Annotated[dict[str, str | int], Depends(get_current_user)],
) -> UserResponse:
    return UserResponse(id=int(current_user["id"]), email=str(current_user["email"]))


@app.post("/items", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemCreate) -> ItemResponse:
    global next_item_id

    item = ItemResponse(id=next_item_id, name=payload.name, price=payload.price)
    items[next_item_id] = item
    next_item_id += 1
    return item


@app.get("/items/{item_id}", response_model=ItemResponse)
def read_item(item_id: int) -> ItemResponse:
    item = items.get(item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found",
        )
    return item


@app.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int) -> Response:
    if item_id not in items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found",
        )

    del items[item_id]
    return Response(status_code=status.HTTP_204_NO_CONTENT)
