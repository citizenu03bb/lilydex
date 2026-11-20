"""The binder import's background worker, wired to the app's own services.

``pokeprice-manage --data … binder-worker`` runs it under its systemd unit
(``deploy/pokeprice-import.service``), at a lower priority than the web
service: customers come first (decision 0047). The command line import runs
the same steps in the foreground when no worker holds the lease.
"""

import logging
import os
import signal
import threading

from .binder_import import ACTOR, BinderImports, budget_from_env

logger = logging.getLogger("pokeprice.binder")


def notifier_for(store, environ):
    """Every alert channel the server has (Web Push, e-mail); None without any."""
    from .notifications import channels_from_env

    channels = channels_from_env(environ, store=store)
    if not channels:
        return None
    link = (environ.get("POKEPRICE_PUBLIC_ORIGIN", "") or "").rstrip("/") + "/gestion"

    def notify(title, body):
        for channel in channels:
            try:
                channel.send(title, f"{body}\n{link}", link)
            except Exception as error:  # noqa: BLE001 - One channel down never hides another.
                logger.warning("binder notification failed channel=%s error=%s",
                               channel.name, type(error).__name__)

    return notify


def build(store, environ=None, *, holder=None):
    """The import service with the real readers, checks and review agent."""
    from .agent_review import AgentReview, review_apply
    from .condition_assessment import ConditionService
    from .edition_check import EditionCheckService, EditionSuggester
    from .pricing import fetch_catalogue_card
    from .variant_catalogue import VariantCatalogue
    from .verification import VariantCheckService, check_inputs

    environ = os.environ if environ is None else environ
    variant_checks = VariantCheckService(store)
    edition_checks = EditionCheckService(store)
    conditions = ConditionService(store)
    catalogue = VariantCatalogue(store, fetch_catalogue_card)

    def inputs(copy_id, threshold_cents=1000):
        return check_inputs(store, catalogue, copy_id, threshold_cents)

    review = AgentReview(store, variant_checks, conditions, edition_checks, inputs)

    def checks(copy_id):
        """The intake checks, then the condition: each skips what its photo already has."""
        variant_checks.evaluate_new_copy(copy_id, ACTOR, inputs)
        if edition_checks.available:
            edition_checks.evaluate_new_copy(copy_id, ACTOR)
        with store.connect() as db:
            card = store.get(db, copy_id)
        try:
            conditions.evaluate(copy_id, card["version"], ACTOR)
        except Exception as error:  # noqa: BLE001 - The agent asks again if it needs it.
            logger.info("binder condition reading skipped copy=%s error=%s", copy_id,
                        type(error).__name__)

    def run_review(copy_ids, apply):
        return review.run(apply=apply, read=apply, copy_ids=copy_ids, trigger="import")

    gate = None
    if environ.get("POKEPRICE_IMPORT_ENERGY_GATE", "on") != "off" and edition_checks.available:
        try:
            from .energy_gate import from_store

            candidate = from_store(store)
            gate = candidate if candidate.ready else None
        except Exception as error:  # noqa: BLE001 - Without the gate, energies are read.
            logger.info("binder energy gate off error=%s", type(error).__name__)
    return BinderImports(
        store,
        suggest=EditionSuggester(edition_checks) if edition_checks.available else None,
        checks=checks,
        review=run_review,
        apply=lambda: review_apply(store),
        notify=notifier_for(store, environ),
        gate=gate,
        default_budget_eur=budget_from_env(environ),
        holder=holder,
    )


def run_worker(imports, stop=None, idle_seconds=5.0):
    """Work until stopped (SIGTERM from systemd stops after the current step)."""
    stop = stop or threading.Event()
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
    logger.info("binder worker started")
    try:
        while not stop.is_set():
            try:
                work = imports.step()
            except Exception:  # noqa: BLE001 - One bad step never stops the worker.
                logger.exception("binder step failed")
                work = None
                stop.wait(idle_seconds * 6)
            if work is None or work[0] == "budget":
                stop.wait(idle_seconds)
    finally:
        imports.release()
        logger.info("binder worker stopped")
