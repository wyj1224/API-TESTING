from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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
    price: float


class ItemResponse(BaseModel):
    id: int
    name: str
    price: float


security = HTTPBearer(auto_error=False)
app = FastAPI(title="Buggy Shop API")

users: dict[str, dict[str, str | int]] = {}
tokens: dict[str, str] = {}
items: dict[int, ItemResponse] = {}
next_user_id = 1
next_item_id = 1


@app.exception_handler(RequestValidationError)
async def buggy_validation_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    missing_password = any(
        error.get("type") == "missing" and error.get("loc") == ("body", "password")
        for error in exc.errors()
    )
    if request.url.path == "/login" and missing_password:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Password validation crashed"},
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> dict[str, str | int]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token parser crashed",
        )

    email = tokens.get(credentials.credentials)
    if email is None or email not in users:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        )
    return users[email]


@app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> UserResponse:
    global next_user_id

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

    token = f"buggy-token-{payload.email}"
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
        return ItemResponse(id=item_id, name="missing item placeholder", price=0)
    return item


@app.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int) -> Response:
    if item_id in items:
        del items[item_id]
    return Response(status_code=status.HTTP_204_NO_CONTENT)
