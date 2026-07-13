from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import positions, trips, vehicles, webhook, zones

app = FastAPI(title="MineSight API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten once auth/orgs land
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vehicles.router)
app.include_router(positions.router)
app.include_router(webhook.router)
app.include_router(zones.router)
app.include_router(trips.router)


@app.get("/health")
def health():
    return {"status": "ok"}
