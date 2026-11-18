"""Checks queued after a response, shared by the capture, intake and photo routes."""

from collections.abc import Callable
from typing import NamedTuple

from .context import AppContext


class Hooks(NamedTuple):
    read_after_intake: Callable[..., None]
    review_after_photo: Callable[..., None]


def build_hooks(ctx: AppContext, auto_checks) -> Hooks:
    """The background checks ``create_app`` queued, over the same shared services."""
    variant_checks = ctx.variant_checks
    edition_checks = ctx.edition_checks
    variant_inputs = ctx.variant_inputs
    review = ctx.review

    def read_after_intake(tasks, card, user):
        """A new photographed copy is checked once, after the response."""
        if auto_checks and card.get("photo"):
            tasks.add_task(
                variant_checks.evaluate_new_copy,
                card["id"],
                user["username"],
                variant_inputs,
            )
            if edition_checks.available:
                tasks.add_task(
                    edition_checks.evaluate_new_copy, card["id"], user["username"]
                )

    def review_after_photo(tasks, copy_id):
        """A new photo answering a request is read again after the response."""
        if auto_checks:
            tasks.add_task(review.after_photo, copy_id)

    return Hooks(read_after_intake, review_after_photo)
