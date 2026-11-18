"""Waivers under the anti-undercut floor, decided by a person (decision 0030)."""

from fastapi import Depends

from ..schemas import FloorDecision
from .context import AppContext


def register_floor_requests(app, ctx: AppContext):
    """Register the floor request routes on ``app``, where ``create_app`` had them."""
    floor_requests = ctx.floor_requests
    staff = ctx.auth.staff
    editor = ctx.auth.editor

    @app.get("/api/floor-requests")
    def floor_request_index(user=Depends(staff)):
        return floor_requests.open()

    @app.post("/api/floor-requests/{request_id}/accept")
    def floor_request_accept(request_id: str, values: FloorDecision, user=Depends(editor)):
        return floor_requests.accept(request_id, user["username"], values.reason)

    @app.post("/api/floor-requests/{request_id}/raise")
    def floor_request_raise(request_id: str, values: FloorDecision, user=Depends(editor)):
        return floor_requests.raise_to_floor(request_id, user["username"], values.reason)

    @app.post("/api/floor-requests/{request_id}/refuse")
    def floor_request_refuse(request_id: str, values: FloorDecision, user=Depends(editor)):
        return floor_requests.refuse(request_id, user["username"], values.reason)
