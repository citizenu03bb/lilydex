"""Request bodies of the web application, validated by FastAPI.

No ``from __future__ import annotations`` here: FastAPI reads these annotations
at route registration, and postponed annotations would hide them.
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PhotoOptions(Model):
    crop: StrictBool = True
    balance: StrictBool = True
    perspective: StrictBool = True


class PhotoAttachment(Model):
    token: str = Field(min_length=20, max_length=100)
    expected_version: int = Field(ge=1)
    side: Literal["front", "back"] = "front"


class ConditionRequest(Model):
    expected_version: int = Field(ge=1)


class MarketVerdict(Model):
    expected_version: int = Field(ge=1)
    verdict: Literal["wrong", "verified", ""]
    reason: str = Field(min_length=1, max_length=1000)


class BoundQuote(Model):
    expected_version: int = Field(ge=1)
    metrics: dict[str, Decimal]
    observed_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    capture_sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    reason: str = Field(min_length=1, max_length=1000)


class OffersPaste(Model):
    text: str = Field(min_length=1, max_length=200_000)


class ConditionConfirmation(ConditionRequest):
    condition: Literal["NM", "EX", "GD", "LP", "PL", "PO", "NM/EX"]
    human_confirmed: Literal[True]
    reason: str = Field(min_length=1, max_length=1000)


class VariantDecision(ConditionRequest):
    finish: Literal["non_holo", "holo", "holo_border", "reverse", "special"]
    stamp_state: Literal["unobserved", "absent", "present"]
    stamp: str = Field(default="", max_length=120)
    variant_confirmed: bool
    reason: str = Field(min_length=1, max_length=1000)


class KeepRecorded(ConditionRequest):
    reason: str = Field(min_length=1, max_length=1000)


class Credentials(Model):
    # E-mail addresses serve as client usernames, "+" included.
    username: str = Field(min_length=1, max_length=254, pattern=r"^[\w.@+-]+$")
    password: str = Field(min_length=10, max_length=256)


class UserCreate(Credentials):
    role: Literal["admin", "editor", "reader"] = "reader"


class UserPatch(Model):
    role: Literal["admin", "editor", "reader"]
    disabled: bool = False


class PushKeys(Model):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class PushEndpoint(Model):
    endpoint: str = Field(min_length=1, max_length=1024)


class PushSubscription(PushEndpoint):
    keys: PushKeys


class CardFields(Model):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    set_name: str | None = Field(default=None, max_length=256)
    number: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, pattern=r"^(?:[a-z]{2,3}|unknown)$")
    catalog_id: str | None = Field(default=None, max_length=120)
    hp: int | None = Field(default=None, ge=0, le=5000)
    identification_status: (
        Literal["confirmed", "review", "unresolved", "failed"] | None
    ) = None
    condition: Literal["", "NM", "EX", "GD", "LP", "PL", "PO", "NM/EX"] | None = None
    condition_confirmed: bool | None = None
    foil: bool | None = None
    finish: (
        Literal["", "non_holo", "holo", "holo_border", "reverse", "special"] | None
    ) = None
    variant_confirmed: bool | None = None
    variant_observation: str | None = Field(default=None, max_length=1000)
    stamp: str | None = Field(default=None, max_length=120)
    stamp_state: Literal["unobserved", "absent", "present"] | None = None
    distribution: str | None = Field(default=None, max_length=120)
    distribution_state: Literal["unobserved", "absent", "present"] | None = None
    album_id: str | None = Field(default=None, min_length=1, max_length=120)
    page: int | None = Field(default=None, ge=1, le=1000)
    position: int | None = Field(default=None, ge=1, le=100)
    notes: str | None = Field(default=None, max_length=8000)


class CardPatch(CardFields):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    reference_price_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    price_source: str | None = Field(default=None, max_length=256)


class CardCreate(CardFields):
    name: str = Field(min_length=1, max_length=256)
    album_id: str = Field(min_length=1, max_length=120)
    page: int = Field(ge=1, le=1000)
    position: int = Field(ge=1, le=100)
    set_name: str = Field(default="", max_length=256)
    number: str = Field(default="", max_length=80)
    language: str = Field(default="fr", pattern=r"^(?:[a-z]{2,3}|unknown)$")
    reason: str = Field(min_length=1, max_length=1000)
    duplicate_acknowledgments: list[str] = Field(default_factory=list, max_length=200)


class CopyRemoval(Model):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class ReferenceDispute(CopyRemoval):
    active: bool
    affects: Literal["print", "market", "both"] = "both"


class AlbumCreate(Model):
    name: str = Field(min_length=1, max_length=120)


class IntakeQuery(Model):
    name: str = Field(min_length=1, max_length=256)
    number: str = Field(default="", max_length=80)
    language: str = Field(default="unknown", pattern=r"^(?:[a-z]{2,3}|unknown)$")
    hp: int | None = Field(default=None, ge=0, le=5000)


class IntakeEntry(Model):
    """The entry as shown when a reading starts: fallback for unread fields."""

    name: str = Field(default="", max_length=256)
    number: str = Field(default="", max_length=80)
    language: str = Field(default="unknown", pattern=r"^(?:[a-z]{2,3}|unknown)$")
    hp: int | None = Field(default=None, ge=0, le=5000)


class IntakeSave(CardCreate):
    chosen_catalog_id: str | None = Field(default=None, max_length=120)
    human_confirmed: bool = False


class CaptureCreate(Model):
    album_id: str = Field(min_length=1, max_length=120)
    slots: int = Field(default=9, ge=1, le=100)
    page: int = Field(default=1, ge=1, le=1000)
    position: int = Field(default=1, ge=1, le=100)


class CaptureFields(CardFields):
    reason: str = Field(default="", max_length=1000)
    chosen_catalog_id: str | None = Field(default=None, max_length=120)
    human_confirmed: bool = False


class CapturePatch(Model):
    expected_version: int = Field(ge=1)
    page: int | None = Field(default=None, ge=1, le=1000)
    position: int | None = Field(default=None, ge=1, le=100)
    fields: CaptureFields | None = None
    front_token: str | None = Field(default=None, min_length=20, max_length=100)
    back_token: str | None = Field(default=None, min_length=20, max_length=100)
    status: Literal["active", "paused", "closed"] | None = None


class CaptureSave(IntakeSave):
    expected_version: int = Field(ge=1)
    token: str = Field(min_length=20, max_length=100)


class BatchCopy(Model):
    id: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


class BatchPreview(Model):
    copies: list[BatchCopy] = Field(min_length=1, max_length=20)
    side: Literal["front", "back"] = "front"
    options: PhotoOptions = Field(default_factory=PhotoOptions)


class BatchApply(Model):
    copy_ids: list[str] = Field(default_factory=list, max_length=20)
    positions: list[int] = Field(default_factory=list, max_length=9)


class MovePreview(Model):
    copies: list[BatchCopy] = Field(min_length=1, max_length=200)
    album_id: str = Field(min_length=1, max_length=120)
    mode: Literal["auto", "from_slot"] = "auto"
    start_page: int = Field(default=1, ge=1, le=1000)
    start_position: int = Field(default=1, ge=1, le=100)
    slots: int = Field(default=9, ge=1, le=100)
    reason: str = Field(default="Déplacement groupé", min_length=1, max_length=1000)


class MoveApply(Model):
    reason: str | None = Field(default=None, min_length=1, max_length=1000)
    allow_collisions: bool = False


class MoveUndo(Model):
    reason: str | None = Field(default=None, min_length=1, max_length=1000)


def intake_values(values):
    data = values.model_dump(
        exclude_unset=True,
        exclude={
            "expected_version",
            "token",
            "duplicate_acknowledgments",
            "chosen_catalog_id",
            "human_confirmed",
            "catalog_id",
            "identification_status",
            "condition",
            "condition_confirmed",
            "foil",
        },
    )
    if any(v is None and k != "hp" for k, v in data.items()):
        raise ValueError("Champ vide non autorisé.")
    for key in ("name", "number", "set_name", "language", "reason"):
        data[key] = getattr(values, key)
    return data


class Signup(Model):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=256)
    # Acknowledges the data notice; the legal basis is the reservation itself,
    # not consent. Its date stays in users.consent_at.
    consent: Literal[True]


class BasketQuote(Model):
    listing_ids: list[str] = Field(min_length=1, max_length=50)
    delivery: Literal["shipping", "hand"] = "shipping"


class RequestCreate(BasketQuote):
    expected_prices: dict[str, Annotated[int, Field(strict=True, ge=0)]] = Field(max_length=50)
    message: str = Field(default="", max_length=1000)
    registered: bool | None = None


class GuestRequest(RequestCreate):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=80)
    # The same notice as at signup: the reservation itself is the legal basis.
    consent: Literal[True]


class PasswordSet(Model):
    token: str = Field(min_length=20, max_length=100)
    password: str = Field(min_length=10, max_length=256)


class RequestVersion(Model):
    expected_version: int = Field(ge=1)


class RequestAccept(RequestVersion):
    listing_ids: list[str] = Field(min_length=1, max_length=50)


class RequestContact(RequestVersion):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=80)
    correspondence_checked: Literal[True]


class Profile(Model):
    display_name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PasswordCheck(Model):
    password: str = Field(min_length=1, max_length=256)


class PaymentSettings(Model):
    # Each method is optional; an empty value means it is not offered.
    wero: str = Field("", max_length=254)
    iban: str = Field("", max_length=64)
    holder: str = Field("", max_length=70)
    paypal: str = Field("", max_length=254)


class FloorMarginSettings(Model):
    margin: int = Field(ge=0, le=50, strict=True)


class LotRotationSettings(Model):
    days: int = Field(ge=3, le=90, strict=True)


class ClientPatch(Model):
    status: Literal["active", "refused"]
    disabled: bool = False


class ListingPrice(Model):
    # Without a price, the copy takes its computed storefront price.
    price_eur: Decimal | None = Field(default=None, ge=0, le=10000000, decimal_places=2)


class FloorDecision(Model):
    reason: str = Field(default="", max_length=1000)


class ListingCreate(ListingPrice):
    copy_ids: list[str] = Field(min_length=1, max_length=401)
    lot: bool = False
    title: str = Field(default="", max_length=256)


class SaleCreate(Model):
    title: str = Field(min_length=1, max_length=256)
    copy_ids: list[str] = Field(min_length=1, max_length=401)
    amount_eur: Decimal = Field(ge=0, le=10000000, decimal_places=2)
    asking_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    target_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    minimum_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    channel: str = Field(default="", max_length=120)
    listing_url: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=8000)


class SalePatch(Model):
    expected_version: int = Field(ge=1)
    asking_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    target_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    minimum_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    reason: str = Field(min_length=1, max_length=1000)
    status: (
        Literal[
            "draft", "reserved", "sold", "shipped", "completed", "cancelled", "returned"
        ]
        | None
    ) = None
    amount_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    fees_eur: Decimal | None = Field(default=None, ge=0, le=10000000, decimal_places=2)
    shipping_charged_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    shipping_cost_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    packing_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    refund_eur: Decimal | None = Field(
        default=None, ge=0, le=10000000, decimal_places=2
    )
    paid: bool | None = None
    channel: str | None = Field(default=None, max_length=120)
    listing_url: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=8000)
