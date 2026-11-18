"""The application's error answers: the visitor-facing codes and the exception handlers.

``install_handlers`` must run before ``agent_api.install``, which keeps the
``Conflict`` and ``ValueError`` handlers registered here as its fallbacks.
"""

import json

from fastapi import FastAPI, HTTPException, Response
from fastapi.exception_handlers import http_exception_handler

from .floor_requests import HumanOnly
from .inventory import Conflict
from .reservations import BasketConflict

# The errors a storefront visitor can meet, by their French detail. The answer adds
# the code; the storefront shows web/messages' "error.<code>" in its own language.
ERROR_CODES = {
    "Origine interdite.": "origin_forbidden",
    "Trop de requêtes. Réessayez dans une minute.": "too_many_requests",
    "Trop d’inscriptions depuis cette adresse. Réessayez plus tard.": "too_many_signups",
    "Trop de demandes depuis cette adresse. Réessayez plus tard.": "too_many_guest_requests",
    "Trop de tentatives. Réessayez dans cinq minutes.": "too_many_attempts",
    "Connectez-vous pour consulter la collection.": "login_required",
    "Espace réservé aux comptes clients.": "clients_only",
    "Identifiants incorrects.": "wrong_credentials",
    "Compte en attente de validation.": "account_pending",
    "Mot de passe incorrect.": "wrong_password",
    "Adresse e-mail invalide.": "invalid_email",
    "Cette adresse est déjà utilisée par un autre compte.": "email_taken",
    "Ce lien n’est plus valable : demandez-en un autre au vendeur.": "link_expired",
    "La boutique n’est pas encore ouverte aux inscriptions.": "signup_closed",
    "La boutique n’est pas encore ouverte aux réservations.": "requests_closed",
    "Carte absente de la vitrine.": "card_not_found",
    "Choisissez des cartes distinctes.": "duplicate_cards",
    "Votre sélection a changé : vérifiez les prix et les disponibilités.": "basket_changed",
    "Trop de demandes en attente : attendez une réponse du vendeur.": "too_many_pending",
    "Demande introuvable.": "request_not_found",
    "La demande a changé. Actualisez la page.": "request_changed",
    "Seule une demande en attente peut être annulée.": "request_not_pending",
    "Format d’image indisponible.": "photo_format_unavailable",
}


def error_response(detail, status_code, headers=None):
    body = {"detail": detail}
    if detail in ERROR_CODES:
        body["code"] = ERROR_CODES[detail]
    return Response(
        json.dumps(body), status_code=status_code, headers=headers, media_type="application/json"
    )


def install_handlers(app: FastAPI) -> None:
    """Register the domain exception handlers on the application."""
    @app.exception_handler(HTTPException)
    async def refused(request, exc):
        if isinstance(exc.detail, str):
            return error_response(exc.detail, exc.status_code, exc.headers)
        return await http_exception_handler(request, exc)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        if isinstance(exc, BasketConflict):
            return Response(json.dumps({
                "detail": str(exc), "code": "basket_changed", "quote": exc.quote,
                "changed": exc.changed, "unavailable": exc.quote["unavailable"],
            }), status_code=409, media_type="application/json")
        return error_response(str(exc), 409)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return error_response(str(exc.args[0]), 404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return error_response(str(exc), 422)

    @app.exception_handler(HumanOnly)
    async def human_only(request, exc):
        return error_response(str(exc), 403)
