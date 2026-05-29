from fastapi import FastAPI
from auth.router import router

app = FastAPI(title="DS Auth Service")
app.include_router(router, prefix="/auth")
