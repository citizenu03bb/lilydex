"""Condition, variant and edition checks of a stored copy, and photo requests."""

from fastapi import Depends, HTTPException, Query

from ..inventory import cents
from ..schemas import (
    ConditionConfirmation,
    ConditionRequest,
    KeepRecorded,
    VariantDecision,
)
from ..verification import check_rows, propose_variant
from .context import AppContext


def register_conditions(app, ctx: AppContext):
    """Register the condition-assessment routes on ``app``, where ``create_app`` had them."""
    conditions = ctx.conditions
    editor = ctx.auth.editor

    @app.post("/api/copies/{copy_id}/condition-assessments", status_code=201)
    def assess_condition(copy_id: str, values: ConditionRequest, user=Depends(editor)):
        try:
            return conditions.evaluate(
                copy_id, values.expected_version, user["username"]
            )
        except RuntimeError as error:
            raise HTTPException(502, str(error)) from None

    @app.post("/api/copies/{copy_id}/condition-assessments/{assessment_id}/confirm")
    def confirm_condition(
        copy_id: str,
        assessment_id: str,
        values: ConditionConfirmation,
        user=Depends(editor),
    ):
        return conditions.confirm(
            copy_id,
            assessment_id,
            values.expected_version,
            values.condition,
            user["username"],
            values.reason,
        )


def register_checks(app, ctx: AppContext):
    """Register the photo-request, variant and edition check routes, where ``create_app`` had them."""
    store = ctx.store
    variant_checks = ctx.variant_checks
    edition_checks = ctx.edition_checks
    variant_inputs = ctx.variant_inputs
    review = ctx.review
    staff = ctx.auth.staff
    editor = ctx.auth.editor

    @app.get("/api/photo-requests")
    def photo_requests(user=Depends(staff)):
        return review.photo_requests()

    @app.post("/api/copies/{copy_id}/variant-checks", status_code=201)
    def check_variant(
        copy_id: str,
        values: ConditionRequest,
        threshold: float = Query(default=10, ge=0.01, le=10000),
        user=Depends(editor),
    ):
        snapshot, valuation = variant_inputs(copy_id, cents(threshold))
        try:
            return variant_checks.evaluate(
                copy_id,
                values.expected_version,
                user["username"],
                snapshot=snapshot,
                valuation=valuation,
            )
        except RuntimeError as error:
            raise HTTPException(502, str(error)) from None

    @app.post("/api/copies/{copy_id}/variant-checks/{check_id}/confirm")
    def confirm_variant(
        copy_id: str,
        check_id: str,
        values: VariantDecision,
        threshold: float = Query(default=10, ge=0.01, le=10000),
        user=Depends(editor),
    ):
        snapshot, valuation = variant_inputs(copy_id, cents(threshold))
        with store.connect() as db:
            card = store.get(db, copy_id)
            row = next((r for r in check_rows(db, card) if r["id"] == check_id), None)
        proposal = (
            propose_variant(card, row["result"], snapshot, valuation) if row else None
        )
        return variant_checks.confirm(
            copy_id,
            check_id,
            values.expected_version,
            values.model_dump(exclude={"expected_version", "reason"}),
            user["username"],
            values.reason,
            proposal,
        )

    @app.post("/api/copies/{copy_id}/variant-checks/{check_id}/keep-language")
    def keep_language(
        copy_id: str, check_id: str, values: KeepRecorded, user=Depends(editor)
    ):
        return variant_checks.keep_language(
            copy_id, check_id, values.expected_version, user["username"], values.reason
        )

    @app.post("/api/copies/{copy_id}/edition-checks", status_code=201)
    def check_edition(copy_id: str, values: ConditionRequest, user=Depends(editor)):
        if not edition_checks.available:
            raise HTTPException(
                503,
                "Contrôle d’édition indisponible : installez l’option vision (uv sync --extra vision).",
            )
        try:
            return edition_checks.evaluate(
                copy_id, values.expected_version, user["username"]
            )
        except RuntimeError as error:
            raise HTTPException(502, str(error)) from None

    @app.post("/api/copies/{copy_id}/edition-checks/{check_id}/keep")
    def keep_edition(
        copy_id: str, check_id: str, values: KeepRecorded, user=Depends(editor)
    ):
        return edition_checks.keep(
            copy_id, check_id, values.expected_version, user["username"], values.reason
        )
