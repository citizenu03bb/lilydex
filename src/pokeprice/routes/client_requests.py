"""The clients' purchase requests, as the management sees and decides them."""

from fastapi import Depends

from ..schemas import CopyRemoval, RequestAccept, RequestContact
from .context import AppContext


def register_client_requests(app, ctx: AppContext):
    """Register the client request routes on ``app``, where ``create_app`` had them."""
    reservations = ctx.reservations
    staff = ctx.auth.staff
    editor = ctx.auth.editor
    admin = ctx.auth.admin

    @app.get("/api/requests")
    def request_index(user=Depends(staff)):
        return reservations.all()

    @app.post("/api/requests/{request_id}/accept")
    def request_accept(request_id: str, values: RequestAccept, user=Depends(editor)):
        return reservations.accept(
            request_id, values.expected_version, values.listing_ids, user["username"]
        )

    @app.patch("/api/requests/{request_id}/contact")
    def request_contact(request_id: str, values: RequestContact, user=Depends(admin)):
        return reservations.confirm_contact(request_id, values.expected_version, values.email,
                                            values.display_name, user["username"])

    @app.post("/api/requests/{request_id}/refuse")
    def request_refuse(request_id: str, values: CopyRemoval, user=Depends(editor)):
        return reservations.refuse(
            request_id, values.expected_version, user["username"], values.reason
        )
