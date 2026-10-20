"""Small, separately authenticated HTTP contract for delegated collection agents."""

import re
import threading
import time
import uuid
from collections import OrderedDict, deque
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from .agent import AgentError, AgentService, digest
from .library import normalized

PREFIX = "/api/agent/v1"


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class ExpectedCopy(AgentModel):
    id: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)


class ApprovedCorrection(AgentModel):
    expected_version: int = Field(ge=1)
    approval_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SaleDraft(AgentModel):
    title: str = Field(min_length=1, max_length=256)
    copies: list[ExpectedCopy] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=8000)
    keep_per_reference: int = Field(default=1, ge=1, le=10)


class BoundedRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            if request.method == "POST":
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 65536:
                        raise AgentError(
                            413, "request_too_large", "Requête limitée à 64 Ko."
                        )
                    body.extend(chunk)
                # The same Request is passed to FastAPI's parser, which reuses its cached body.
                request._body = bytes(body)
            return await handler(request)

        return bounded


class RateLimit:
    """Bounded process-local limiter; no credentials are retained as keys."""

    def __init__(self):
        self.buckets = OrderedDict()
        self.lock = threading.Lock()

    def check(self, key, maximum=60):
        now = time.monotonic()
        with self.lock:
            bucket = self.buckets.pop(key, deque())
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= maximum:
                self.buckets[key] = bucket
                raise AgentError(
                    429, "rate_limited", "Trop de requêtes ; réessayez dans une minute."
                )
            bucket.append(now)
            self.buckets[key] = bucket
            if len(self.buckets) > 4096:
                self.buckets.popitem(last=False)


def router(service):
    api = APIRouter(prefix=PREFIX, tags=["agent-v1"], route_class=BoundedRoute)
    limiter = RateLimit()

    def agent_principal(request: Request):
        request.state.agent_request_id = str(uuid.uuid4())
        remote = request.client.host if request.client else "unknown"
        limiter.check("ip:" + remote, 300)
        if request.cookies:
            raise AgentError(
                401, "ambiguous_identity", "Utilisez le jeton agent sans cookie."
            )
        authorization = request.headers.get("authorization", "")
        if not re.fullmatch(r"Bearer pp_agent_[A-Za-z0-9_-]{43}", authorization):
            limiter.check("invalid:" + remote, 30)
            raise AgentError(401, "unauthenticated", "Jeton Bearer agent requis.")
        hashed = digest(authorization[7:])
        try:
            with service.store.connect() as db:
                grant = service.authorize(db, hashed)
        except AgentError:
            limiter.check("invalid:" + remote, 30)
            raise
        limiter.check(grant["id"])
        request.state.agent_token_hash = hashed
        return grant

    def read_transaction(request, permission="copies:read"):
        # Each route rechecks under its own snapshot/transaction, not only in Depends.
        return request.state.agent_token_hash, permission

    principal = Depends(agent_principal)

    @api.get("/capabilities")
    def capabilities(request: Request, grant=principal):
        operations = ["copies", "copy", "prepare-lot", "draft"]
        if "photos:read" in grant["permissions"]:
            operations.extend(["photo", "package"])
        if "drafts:create" in grant["permissions"]:
            operations.append("create-draft")
        if "corrections:apply" in grant["permissions"]:
            operations.extend(["corrections", "apply-correction"])
        return {
            "contract_version": "1",
            "agent_id": grant["id"],
            "name": grant["name"],
            "album_id": grant["album_id"],
            "client": grant["client"],
            "permissions": sorted(grant["permissions"]),
            "expires_at": grant["expires_at"],
            "value_ceiling_cents": grant["value_ceiling_cents"],
            "limits": {
                "copies_per_page": 100,
                "copies_per_draft": 20,
                "requests_per_minute": 60,
            },
            "operations": operations,
            "request_id": request.state.agent_request_id,
        }

    @api.get("/copies")
    def copies(
        request: Request,
        q: str = Query(default="", max_length=300),
        limit: int = Query(default=60, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=2000),
        grant=principal,
    ):
        with service.store.connect() as db:
            db.execute("BEGIN")
            grant = service.authorize(db, *read_transaction(request))
            cards = service.facts(db, grant)
            terms = normalized(q).split()
            cards = [
                c
                for c in cards
                if all(
                    t
                    in normalized(
                        " ".join(
                            str(c[k] or "")
                            for k in (
                                "name",
                                "set_name",
                                "number",
                                "language",
                                "catalog_id",
                            )
                        )
                    )
                    for t in terms
                )
            ]
            return {
                "items": cards[offset : offset + limit],
                "total": len(cards),
                "offset": offset,
                "limit": limit,
                "request_id": request.state.agent_request_id,
            }

    @api.get("/copies/{copy_id}")
    def copy_detail(copy_id: str, request: Request, grant=principal):
        with service.store.connect() as db:
            db.execute("BEGIN")
            grant = service.authorize(db, *read_transaction(request))
            service.scoped_card(db, grant, copy_id)
            return next(c for c in service.facts(db, grant) if c["id"] == copy_id)

    @api.get("/copies/{copy_id}/photo")
    def photo(
        copy_id: str,
        request: Request,
        side: Literal["front", "back"] = "front",
        grant=principal,
    ):
        with service.store.connect() as db:
            db.execute("BEGIN")
            grant = service.authorize(db, *read_transaction(request, "photos:read"))
            card = service.scoped_card(db, grant, copy_id)
            name = card["photo" if side == "front" else "back_photo"]
            if not name or not re.fullmatch(r"[a-f0-9]{64}\.jpg", name):
                raise AgentError(404, "not_found", "Photo absente.")
            path = service.store.photos / name
            if not path.is_file():
                raise AgentError(404, "not_found", "Photo absente.")
        return FileResponse(
            path, media_type="image/jpeg", headers={"X-Photo-SHA256": name[:-4]}
        )

    @api.get("/prepare-lot")
    def prepare_lot(
        request: Request,
        keep: int = Query(default=1, ge=1, le=10),
        maximum: int = Query(default=20, ge=1, le=20),
        language: str = Query(default="", pattern=r"^(?:[a-z]{2,3})?$"),
        grant=principal,
    ):
        with service.store.connect() as db:
            db.execute("BEGIN")
            grant = service.authorize(db, *read_transaction(request))
            return {
                **service.prepare(
                    service.facts(db, grant),
                    keep=keep,
                    maximum=maximum,
                    language=language,
                ),
                "album_id": grant["album_id"],
                "request_id": request.state.agent_request_id,
            }

    @api.post("/drafts", status_code=201)
    def create_draft(
        values: SaleDraft,
        request: Request,
        key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=120)
        ],
        grant=principal,
    ):
        return service.create_draft(
            request.state.agent_token_hash,
            key,
            values.model_dump(),
            request.state.agent_request_id,
        )

    @api.get("/corrections")
    def approved_corrections(request: Request, grant=principal):
        from .agent_corrections import CorrectionService

        with service.store.connect() as db:
            db.execute("BEGIN")
            return CorrectionService(service.store).pending(
                db, request.state.agent_token_hash
            )

    @api.post("/copies/{copy_id}/apply-correction")
    def apply_correction(
        copy_id: str, values: ApprovedCorrection, request: Request, grant=principal
    ):
        from .agent_corrections import CorrectionService

        return CorrectionService(service.store).apply(
            request.state.agent_token_hash,
            copy_id,
            values.expected_version,
            values.approval_sha256,
            request.state.agent_request_id,
        )

    @api.get("/drafts/{sale_id}")
    def get_draft(sale_id: str, request: Request, grant=principal):
        with service.store.connect() as db:
            db.execute("BEGIN")
            grant = service.authorize(db, *read_transaction(request))
            return service.get_draft(db, grant, sale_id)

    @api.get("/drafts/{sale_id}/package")
    def draft_package(sale_id: str, request: Request, grant=principal):
        import shutil
        import tempfile
        from pathlib import Path

        from starlette.background import BackgroundTask

        from .listing_package import package

        with service.store.connect() as db:
            db.execute("BEGIN")
            grant = service.authorize(db, *read_transaction(request, "photos:read"))
            draft = service.get_draft(db, grant, sale_id)
            if draft["status"] != "draft":
                raise AgentError(
                    403, "forbidden", "Ce lot n’est plus un brouillon agent."
                )
            # Pass this authorized snapshot to the generator: no fresh, unscoped read.
            cards = [service.scoped_card(db, grant, c["id"]) for c in draft["copies"]]
            sale = dict(
                db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
            )
        folder = Path(tempfile.mkdtemp(prefix="pokeprice-agent-package-"))
        try:
            target = folder / "annonce.zip"
            package(service.store, sale_id, target, snapshot=(sale, cards, draft))
        except BaseException:
            shutil.rmtree(folder)
            raise
        return FileResponse(
            target,
            filename="brouillon-agent.zip",
            media_type="application/zip",
            background=BackgroundTask(shutil.rmtree, folder),
        )

    return api


def schema():
    """Offline, agent-only schemas; no collection database is opened."""
    contract = get_openapi(
        title="Pokeprice — API agent", version="1", routes=router(None).routes
    )
    contract.setdefault("components", {})["securitySchemes"] = {
        "AgentBearer": {
            "type": "http",
            "scheme": "bearer",
            "description": "Jeton délégué, sans cookie utilisateur.",
        }
    }
    contract["security"] = [{"AgentBearer": []}]
    return contract


def install(app, store):
    from fastapi.exception_handlers import request_validation_exception_handler
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    from .inventory import Conflict

    app.state.agents = AgentService(store)
    app.include_router(router(app.state.agents))

    for kind, code, status in (
        (Conflict, "version_conflict", 409),
        (ValueError, "invalid_request", 422),
    ):
        previous = app.exception_handlers[kind]

        async def domain_error(
            request, exc, code=code, status=status, previous=previous
        ):
            if not request.url.path.startswith(PREFIX + "/"):
                return await previous(request, exc)
            return JSONResponse(
                {
                    "code": code,
                    "detail": str(exc),
                    "request_id": getattr(
                        request.state, "agent_request_id", str(uuid.uuid4())
                    ),
                },
                status_code=status,
            )

        app.add_exception_handler(kind, domain_error)

    @app.exception_handler(RequestValidationError)
    async def invalid_parameters(request, exc):
        if not request.url.path.startswith(PREFIX + "/"):
            return await request_validation_exception_handler(request, exc)
        return JSONResponse(
            {
                "code": "invalid_request",
                "detail": "Paramètres de requête invalides.",
                "request_id": getattr(
                    request.state, "agent_request_id", str(uuid.uuid4())
                ),
            },
            status_code=422,
        )

    @app.exception_handler(AgentError)
    async def agent_error(request, exc):
        headers = {"Retry-After": "60"} if exc.status == 429 else {}
        return JSONResponse(
            {
                "code": exc.code,
                "detail": str(exc),
                "request_id": getattr(
                    request.state, "agent_request_id", str(uuid.uuid4())
                ),
            },
            status_code=exc.status,
            headers=headers,
        )
