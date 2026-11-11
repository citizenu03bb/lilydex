#!/usr/bin/env python3
"""Gestion et rotation des lots de doublons pour Les cartes de Lily (pokeprice).

Sous-commandes CLI :
- analyze : examine les doublons et propose des lots thématiques cohérents.
- status  : inspecte les brouillons de vente actifs et la fenêtre de rotation.
- rotate  : applique la rotation (FIFO sur les anciens brouillons hors vitrine si le
            plafond est atteint, création des nouveaux brouillons).
- compose : compose un lot sur mesure à partir d'une recette ou d'un prompt.
- publish-to-storefront : publie un ou tous les brouillons valides en vitrine.

Deux modes, l'un ou l'autre :

- ``--api`` (chemin des agents) : chaque sous-commande passe par les routes ``/api/agent/v1/lots``
(``pokeprice.agent_client``) au lieu d'ouvrir une base : le serveur compose, fixe
l'auteur et le prix plancher. L'interprétation d'un prompt par Gemini reste sur
le poste, qui envoie la recette.
- ``--data`` (chemin de l'opérateur) : le script ouvre lui-même la base désignée,
  là où elle vit (sur le serveur, sous le compte de service ; pour un essai, une
  base temporaire).

Ce script n'est qu'un adaptateur : options, connexions et transactions. Les règles
vivent dans le paquet ``pokeprice.lots`` (gisement, rotation, publication) et
l'interprétation d'un prompt par Gemini dans ``pokeprice.lots_prompt``.
"""

import argparse
import json
import os
import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from pokeprice.agent_client import AgentClient, load_token  # noqa: E402
from pokeprice.inventory import Store  # noqa: E402
from pokeprice.listings import FloorRefusal  # noqa: E402
from pokeprice.lots.engine import (  # noqa: E402
    BONUS_MAX_PER_LOT,
    DEFAULT_ACTOR,
    LOT_EXCLUSIONS,
    MAX_ROTATION_DRAFTS,
    VALUE_CEILING_CENTS,
    bonus_room,
    bonus_title,
)
from pokeprice.lots.engine import LotsEngine as Engine  # noqa: E402
from pokeprice.lots.recipe import (  # noqa: E402
    BundleRules,
    DiversityStrategy,
    HardFilters,
    LotCompositionRecipe,
    ScoringHeuristics,
    ValueIntent,
)
from pokeprice.lots.themes import (  # noqa: E402
    CONDITION_RANKS,
    ICONIC_POKEMON,
    KANTO_POKEMON_NAMES,
    THEME_PATTERNS,
    TRAINER_KEYWORDS,
    categorize_card,
    is_energy,
    is_trainer,
    normalize_pokemon_name,
)
from pokeprice.lots_prompt import (  # noqa: E402
    DEFAULT_GEMINI_MODEL,
    GEMINI_MODEL_ENV,
    gemini_model,
    prompt_to_recipe,
)
from pokeprice.pricing import lot_floor_cents, lot_max_margin  # noqa: E402

# Noms repris du paquet, que les tests et les habitudes importent d'ici.
__all__ = [
    "BONUS_MAX_PER_LOT",
    "CONDITION_RANKS",
    "DEFAULT_ACTOR",
    "DEFAULT_GEMINI_MODEL",
    "GEMINI_MODEL_ENV",
    "ICONIC_POKEMON",
    "KANTO_POKEMON_NAMES",
    "LOT_EXCLUSIONS",
    "MAX_ROTATION_DRAFTS",
    "THEME_PATTERNS",
    "TRAINER_KEYWORDS",
    "VALUE_CEILING_CENTS",
    "BundleRules",
    "DiversityStrategy",
    "HardFilters",
    "LotCompositionRecipe",
    "LotsEngine",
    "ScoringHeuristics",
    "ValueIntent",
    "bonus_room",
    "bonus_title",
    "categorize_card",
    "gemini_model",
    "is_energy",
    "is_trainer",
    "lot_floor_cents",
    "lot_max_margin",
    "main",
    "normalize_pokemon_name",
    "prompt_to_recipe",
    "resolve_db_path",
    "run_api_command",
]


class LotsEngine:
    """Le moteur des lots sur une base désignée par son chemin, pour la ligne de commande.

    Ouvre les connexions et les transactions, puis délègue au moteur du paquet
    (``pokeprice.lots.engine.LotsEngine``). Les méthodes qui prennent déjà une
    connexion (``classify_pool(db)``, ``bulk_bonus_pool(db)``…) sont celles du moteur.
    """

    def __init__(self, db_path, *, value_ceiling_cents=VALUE_CEILING_CENTS):
        self.db_path = str(db_path)
        self.value_ceiling_cents = value_ceiling_cents
        self._store = None
        self._engine = None

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.engine(), name)

    def store(self):
        if self._store is None:
            self._store = Store(str(Path(self.db_path).parent))
        return self._store

    def engine(self):
        if self._engine is None:
            self._engine = Engine(self.store(), value_ceiling_cents=self.value_ceiling_cents)
        return self._engine

    def connect(self, write=False):
        """Connexion à la base : lecture seule, ou transaction d'écriture."""
        return self.store().connect(write=write)

    def add_bonus(self, lots, pool=None):
        if pool is None:
            with self.connect() as db:
                pool = self.engine().bulk_bonus_pool(db)
        return self.engine().add_bonus(lots, pool)

    def analyze(self, max_cards_per_lot=20):
        with self.connect() as db:
            return self.engine().analyze(db, max_cards_per_lot=max_cards_per_lot)

    def status(self, max_drafts=MAX_ROTATION_DRAFTS):
        with self.connect() as db:
            return self.engine().status(db, max_drafts)

    def rotate(
        self,
        lots_to_add=None,
        limit_add=None,
        dry_run=False,
        actor=DEFAULT_ACTOR,
        max_drafts=MAX_ROTATION_DRAFTS,
    ):
        """Rotation FIFO : calculée en lecture, appliquée dans une seule transaction."""
        with self.connect() as db:
            plan = self.engine().plan_rotation(
                db, lots_to_add=lots_to_add, limit_add=limit_add, max_drafts=max_drafts, dry_run=dry_run
            )
        if dry_run:
            return plan.report
        # Une seule transaction : annulations et créations réussissent ou échouent ensemble.
        with self.connect(write=True) as db:
            plan.report["created"] = self.engine().apply_rotation(db, plan, actor)
        return plan.report

    def publish_to_storefront(self, sale_id, actor=DEFAULT_ACTOR, dry_run=False):
        """Remplace les annonces unitaires des cartes du lot par une annonce de lot.

        Toutes les cartes sont vérifiées avant la moindre écriture ; dépublication,
        publication et mise à jour de la vente se font dans une seule transaction.
        En cas d'erreur, rien n'est écrit et les annonces unitaires restent en ligne.
        """
        try:
            with self.connect(write=not dry_run) as db:
                return self.engine().publish_lot(db, sale_id, actor, dry_run=dry_run)
        except FloorRefusal as refusal:
            # La transaction est annulée : la demande s'écrit après, hors essai à blanc.
            if not dry_run:
                self.engine().record_floor_refusal(refusal, actor, sale_id)
            raise

    def publish_all(self, actor=DEFAULT_ACTOR, dry_run=False):
        """Publie chaque brouillon valide qui n'est pas encore en ligne, un par un.

        Chaque lot est atomique : un refus n'empêche pas les autres et ne retire
        aucune annonce unitaire du lot refusé.
        """
        report = {"dry_run": dry_run, "published": [], "refused": [], "skipped": []}
        for draft in reversed(self.status()["active_drafts"]):  # du plus ancien au plus récent
            if draft["online_listing_id"]:
                report["skipped"].append(
                    {"sale_id": draft["id"], "title": draft["title"], "reason": "déjà en ligne"}
                )
                continue
            if not draft["is_valid"]:
                report["skipped"].append(
                    {"sale_id": draft["id"], "title": draft["title"], "reason": "brouillon invalide",
                     "details": draft["invalid_reasons"]}
                )
                continue
            try:
                report["published"].append(
                    self.publish_to_storefront(draft["id"], actor=actor, dry_run=dry_run)
                )
            except (KeyError, ValueError) as exc:
                refused = {"sale_id": draft["id"], "title": draft["title"], "reason": str(exc)}
                if getattr(exc, "request_id", None):
                    refused["floor_request_id"] = exc.request_id
                report["refused"].append(refused)
        return report

    def compose_from_recipe(self, recipe, duplicates=None, pool=None, scope="duplicates"):
        """Constitue un lot à partir d'une recette typée (LotCompositionRecipe)."""
        with self.connect() as db:
            return self.engine().compose_from_recipe(db, recipe, duplicates=duplicates, pool=pool, scope=scope)

    def compose(
        self,
        recipe,
        create_draft=False,
        actor=DEFAULT_ACTOR,
        prompt=None,
        dry_run=False,
        scope="duplicates",
    ):
        """Exécute la composition et optionnellement enregistre le brouillon dans sales."""
        result = self.compose_from_recipe(recipe, scope=scope)
        if not result.get("lot"):
            return result

        lot = result["lot"]
        if create_draft:
            if dry_run:
                result["draft_action"] = "dry_run_simulated"
                result["projected_sale_title"] = lot["title"]
                return result

            with self.connect(write=True) as db:
                result["created_sale_id"] = self.engine().create_draft(db, lot, actor, prompt)
                result["draft_action"] = "created"

        return result


def resolve_db_path(args):
    """Résout le chemin de la base SQLite, toujours donné explicitement par --data."""
    if not args.data:
        raise ValueError("Indiquez la base visée avec --data (aucune base par défaut).")
    p = Path(args.data)
    if p.is_dir():
        return p / "collection.sqlite3"
    return p


def read_recipe(args):
    """La recette de ``compose`` : un fichier ou du JSON, sinon le prompt interprété par Gemini."""
    if args.recipe:
        recipe_raw = args.recipe
        if not recipe_raw.strip().startswith("{") and len(recipe_raw) < 255:
            recipe_path = Path(recipe_raw)
            if recipe_path.exists():
                recipe_raw = recipe_path.read_text(encoding="utf-8")
        return LotCompositionRecipe.model_validate(json.loads(recipe_raw))
    return prompt_to_recipe(args.prompt)


def api_publish_one(client, sale_id, dry_run, key=None):
    """Publie un brouillon de l'outil à sa version vérifiée par le serveur."""
    check = client.lots_publication(sale_id)
    if not check.get("publishable"):
        raise ValueError(check.get("refusal") or "Lot non publiable.")
    return client.lots_publish(sale_id, expected_version=check["version"], dry_run=dry_run, key=key)


def run_api_command(client, args):
    """Chaque sous-commande du script par l'API agent ; le serveur fixe auteur, marge et plafond."""
    if getattr(args, "actor", DEFAULT_ACTOR) != DEFAULT_ACTOR:
        raise ValueError("--actor ne vaut pas avec --api : l'auteur est l'accès agent.")
    if getattr(args, "max_drafts", MAX_ROTATION_DRAFTS) != MAX_ROTATION_DRAFTS:
        raise ValueError("--max-drafts ne vaut pas avec --api : le plafond vient du serveur.")
    command = args.subcommand
    key = getattr(args, "key", None)
    if key and (command in ("analyze", "status") or getattr(args, "all", False)):
        raise ValueError("--key vaut pour une seule écriture : rotate, compose ou une publication.")
    if command == "analyze":
        return client.lots_pool(args.max_per_lot)
    if command == "status":
        return client.lots_status()
    if command == "rotate":
        return client.lots_rotate(dry_run=args.dry_run, limit=args.limit, key=key)
    if command == "compose":
        if args.scope != "duplicates":
            raise ValueError("--scope all ne vaut pas avec --api : seuls les doublons entrent dans un lot.")
        if not args.prompt and not args.recipe:
            raise ValueError("Indiquez --prompt ou --recipe pour compose.")
        plan = client.lots_plan(read_recipe(args).model_dump(mode="json"))
        if not args.create_draft or not plan.get("plan_id"):
            return plan
        if args.dry_run:
            return {**plan, "draft_action": "dry_run_simulated"}
        draft = client.lots_compose(plan["recipe"], plan["plan_id"], key=key)
        return {**plan, "draft": draft, "created_sale_id": draft["sale_id"], "draft_action": "created"}
    # publish-to-storefront
    if not args.all:
        return api_publish_one(client, args.sale_id, args.dry_run, key)
    report = {"dry_run": args.dry_run, "published": [], "refused": [], "skipped": []}
    for draft in reversed(client.lots_status()["active_drafts"]):  # du plus ancien au plus récent
        if not draft.get("tool_made"):
            report["skipped"].append({"sale_id": draft["id"], "reason": "brouillon fait à la main"})
        elif draft["online_listing_id"]:
            report["skipped"].append(
                {"sale_id": draft["id"], "title": draft["title"], "reason": "déjà en ligne"}
            )
        else:
            try:
                report["published"].append(api_publish_one(client, draft["id"], args.dry_run))
            except ValueError as exc:
                refused = {"sale_id": draft["id"], "title": draft["title"], "reason": str(exc)}
                if getattr(exc, "code", ""):
                    refused["code"] = exc.code
                report["refused"].append(refused)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Génération et rotation de lots de doublons Pokémon pour Les cartes de Lily",
        epilog="Deux modes : --api pour les agents (la production passe par l'API agent, "
        "avec le seul jeton des lots) ; --data pour l'opérateur, lancé là où vit la base "
        "(sur le serveur, sous le compte de service).",
    )
    parser.add_argument(
        "--data",
        help="Chemin de l'opérateur : dossier ou fichier de la base SQLite visée, toujours explicite sans --api "
        "(sur le serveur : /srv/pokeprice/inventory ; pour un essai : une base temporaire)",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Chemin des agents : passer par l'API agent (routes /api/agent/v1/lots), "
        "sans base ni accès au serveur ; --data est alors ignoré",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("POKEPRICE_AGENT_URL", "http://127.0.0.1:3820"),
        help="Serveur agent pour --api (défaut : POKEPRICE_AGENT_URL ou l'interface locale)",
    )
    parser.add_argument(
        "--token-file",
        help="Fichier privé (0600) du jeton agent pour --api ; sinon POKEPRICE_AGENT_TOKEN_FILE",
    )
    parser.add_argument(
        "--key",
        help="Avec --api : clé d'idempotence d'un nouvel essai de rotate, compose ou publication "
        "d'un lot (neuve par défaut)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Fichier de sortie JSON obligatoire pour consigner les résultats",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyser les doublons et proposer des lots")
    p_analyze.add_argument(
        "--max-per-lot",
        type=int,
        default=20,
        help="Nombre maximum de cartes par lot (défaut: 20)",
    )

    def max_drafts_option(sub):
        sub.add_argument(
            "--max-drafts",
            type=int,
            default=MAX_ROTATION_DRAFTS,
            help=f"Plafond de brouillons actifs (défaut: {MAX_ROTATION_DRAFTS})",
        )

    # status
    p_status = subparsers.add_parser("status", help="Consulter l'état de la fenêtre de rotation des brouillons")
    max_drafts_option(p_status)

    # rotate
    p_rotate = subparsers.add_parser("rotate", help="Appliquer la rotation glissante des brouillons")
    max_drafts_option(p_rotate)
    p_rotate.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Nombre maximal de nouveaux lots à intégrer (défaut: le plafond --max-drafts)",
    )
    p_rotate.add_argument(
        "--dry-run",
        action="store_true",
        help="Simuler la rotation sans modifier la base de données",
    )
    p_rotate.add_argument(
        "--actor",
        default=DEFAULT_ACTOR,
        help="Identifiant de l'auteur inscrit dans les événements (défaut: pokeprice-lots)",
    )

    # compose
    p_comp = subparsers.add_parser(
        "compose",
        help="Composer un lot de doublons sur-mesure à partir d'un prompt naturel ou d'une recette",
    )
    p_comp.add_argument(
        "--prompt",
        help="Prompt en langage naturel (ex: 'trouve-moi les pépites sous-évaluées')",
    )
    p_comp.add_argument(
        "--recipe",
        help="Chemin vers un fichier JSON ou chaîne JSON contenant une recette LotCompositionRecipe",
    )
    p_comp.add_argument(
        "--create-draft",
        action="store_true",
        help="Créer un brouillon de vente dans la base pour ce lot",
    )
    p_comp.add_argument(
        "--dry-run",
        action="store_true",
        help="Simuler sans écriture en base de données",
    )
    p_comp.add_argument(
        "--actor",
        default=DEFAULT_ACTOR,
        help="Identifiant de l'auteur inscrit dans les événements (défaut: pokeprice-lots)",
    )
    p_comp.add_argument(
        "--scope",
        choices=["duplicates", "all"],
        default="duplicates",
        help="Périmètre de cartes éligibles : 'duplicates' (défaut, uniquement doublons libres) ou 'all' (inclut cartes d'album)",
    )

    # publish-to-storefront
    p_pub = subparsers.add_parser(
        "publish-to-storefront",
        help="Publier un lot en vitrine publique (avec dépublication unitaire automatique)",
    )
    target = p_pub.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--sale-id",
        help="Identifiant UUID du lot de vente à publier en vitrine",
    )
    target.add_argument(
        "--all",
        action="store_true",
        help="Publier chaque brouillon valide qui n'est pas encore en ligne",
    )
    p_pub.add_argument(
        "--dry-run",
        action="store_true",
        help="Simuler la publication sans modifier la base de données",
    )
    p_pub.add_argument(
        "--actor",
        default=DEFAULT_ACTOR,
        help="Identifiant de l'auteur inscrit dans les événements (défaut: pokeprice-lots)",
    )

    args = parser.parse_args(argv)
    if not args.api and not args.data:
        parser.error("indiquez la base visée avec --data, ou passez par --api")

    if args.api:
        try:
            client = AgentClient(args.url, load_token(args.token_file))
            result = run_api_command(client, args)
        except (ValueError, OSError) as exc:
            sys.stderr.write(f"Refus de l'API agent : {exc}\n")
            key = getattr(exc, "idempotency_key", None)
            if key:
                sys.stderr.write(f"Clé d'idempotence de l'essai : {key}\n")
            sys.exit(1)
    else:
        db_path = resolve_db_path(args)
        if not Path(db_path).exists():
            sys.stderr.write(f"Base de données introuvable : {db_path}\n")
            sys.exit(1)

        engine = LotsEngine(db_path)
        if args.subcommand == "analyze":
            result = engine.analyze(max_cards_per_lot=args.max_per_lot)
        elif args.subcommand == "status":
            result = engine.status(max_drafts=args.max_drafts)
        elif args.subcommand == "rotate":
            result = engine.rotate(
                limit_add=args.limit,
                dry_run=args.dry_run,
                actor=args.actor,
                max_drafts=args.max_drafts,
            )
        elif args.subcommand == "compose":
            if not args.prompt and not args.recipe:
                sys.stderr.write("Erreur: Indiquez --prompt ou --recipe pour la commande compose.\n")
                sys.exit(1)

            recipe = read_recipe(args)
            try:
                result = engine.compose(
                    recipe=recipe,
                    create_draft=args.create_draft,
                    actor=args.actor,
                    prompt=args.prompt,
                    dry_run=args.dry_run,
                    scope=getattr(args, "scope", "duplicates"),
                )
            except ValueError as exc:
                sys.stderr.write(f"Composition refusée : {exc}\n")
                sys.exit(1)
        elif args.subcommand == "publish-to-storefront":
            if args.all:
                result = engine.publish_all(actor=args.actor, dry_run=args.dry_run)
            else:
                try:
                    result = engine.publish_to_storefront(
                        sale_id=args.sale_id,
                        actor=args.actor,
                        dry_run=args.dry_run,
                    )
                except (KeyError, ValueError) as exc:
                    sys.stderr.write(f"Publication refusée : {exc}\n")
                    if getattr(exc, "request_id", None):
                        sys.stderr.write(
                            f"Dérogation demandée en gestion (demande {exc.request_id}).\n"
                        )
                    sys.exit(1)

    out_p = Path(args.output)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Succès ! Résultat écrit dans : {out_p.resolve()}")


if __name__ == "__main__":
    main()
