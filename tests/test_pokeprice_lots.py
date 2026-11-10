import json
import sys
from pathlib import Path

import pytest

from pokeprice.inventory import Store, now

# Permettre l'import de scripts/pokeprice_lots.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from pokeprice_lots import (
    BundleRules,
    DiversityStrategy,
    HardFilters,
    LotCompositionRecipe,
    LotsEngine,
    ScoringHeuristics,
    ValueIntent,
    bonus_room,
    categorize_card,
    lot_floor_cents,
    lot_max_margin,
    main,
    normalize_pokemon_name,
    run_remote_command,
)
from pokeprice.reservations import shipping_quote


def add_copy(store, album, position, *, price=100, **overrides):
    """Exemplaire synthétique, chiffré par un relevé TCGdex fictif (aucun appel réseau)."""
    values = {
        "name": "Zarbi L",
        "set_name": "Duels au Sommet",
        "number": "91/106",
        "language": "fr",
        "catalog_id": "dp4-91",
        "identification_status": "confirmed",
        "album_id": album,
        "page": 1,
        "position": position,
        "finish": "non_holo",
        "variant_confirmed": True,
        "stamp_state": "absent",
        "distribution_state": "absent",
        "condition": "EX",
        "reference_cents": price,
        "price_source": "TCGdex",
        "price_date": now(),
    }
    values.update(overrides)
    card = store.create_copy(values, "tester", "Carte de test")
    if price is not None:
        with store.connect(write=True) as db:
            store.event(
                db,
                card["id"],
                "tester",
                "price-snapshot",
                "Prix de test",
                {},
                {
                    "catalog_id": values["catalog_id"],
                    "updated": "2026-10-01",
                    "source": "TCGdex",
                    "variant": "normal",
                    "variants": {"normal": True, "reverse": False},
                    "raw": {"cardmarket": {"trend": price / 100, "avg30": price / 100, "unit": "EUR"}},
                },
            )
    return card


@pytest.fixture
def test_db(tmp_path):
    """Base temporaire : 3 Zarbi L (1 conservé, 2 doublons) et d'autres cartes chiffrées."""
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        db.executemany("INSERT INTO albums VALUES(?,?)", [("a", "Album A"), ("b", "Album B")])
    add_copy(store, "a", 1)
    add_copy(store, "a", 2)
    add_copy(store, "a", 3, name="Évoli", catalog_id="pl2-59", number="59/111", set_name="Rivaux Émergeants")
    add_copy(
        store, "a", 4, price=None, name="À identifier", catalog_id="",
        identification_status="unresolved", number="", set_name="", variant_confirmed=False,
    )
    add_copy(store, "b", 1)
    add_copy(store, "b", 2, name="Unown L", language="en")
    add_copy(store, "b", 3, name="Fossile Dôme", catalog_id="dp5-89", number="89/100")
    db_path = tmp_path / "inventory" / "collection.sqlite3"
    return db_path, store


def test_categorize_card():
    assert categorize_card({"catalog_id": "base1-46", "name": "Salamèche", "finish": "non_holo"}) == "vintage_wotc"
    assert categorize_card({"catalog_id": "dp6-90", "name": "Osselait", "finish": "non_holo"}) == "dp_platine"
    assert categorize_card({"catalog_id": "sm1-120", "name": "Tili", "finish": "non_holo"}) == "dresseurs"
    assert categorize_card({"catalog_id": "hgss2-53", "name": "Férosinge", "finish": "non_holo"}) == "hgss"
    assert categorize_card({"catalog_id": "bw3-52", "name": "Symbios", "finish": "reverse"}) == "brillantes"
    assert categorize_card({"catalog_id": "base1-99", "name": "Énergie Plante", "finish": "non_holo"}) == "energies"


def test_get_duplicates_pool_and_compose_lots(test_db):
    db_path, _ = test_db
    engine = LotsEngine(db_path)

    with engine.connect() as db:
        retained, duplicates = engine.get_duplicates_pool(db)

    # inputs() crée 7 cartes, dont 3 exemplaires de Zarbi L (dp4-91, fr) : 1 conservé + 2 doublons
    assert len(duplicates) >= 2
    zarbi_dups = [d for d in duplicates if d["catalog_id"] == "dp4-91"]
    assert len(zarbi_dups) == 2

    lots = engine.compose_candidate_lots(duplicates, max_cards_per_lot=20)
    assert len(lots) >= 1
    # Zarbi L appartient au bloc dp_platine
    themes = {l["theme"] for l in lots}
    assert "dp_platine" in themes


def test_analyze_command(test_db):
    db_path, _ = test_db
    engine = LotsEngine(db_path)
    res = engine.analyze()

    assert res["total_retained_cards"] >= 1
    assert res["total_excess_duplicates"] >= 2
    assert res["total_candidate_lots"] >= 1


def test_status_and_rotation_fifo(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)

    # Initialement : 0 brouillon actif
    st = engine.status()
    assert st["active_drafts_count"] == 0
    assert st["capacity_available"] == 5

    # Trouver des exemplaires disponibles pour les tests
    with store.connect() as db:
        copies = [r["id"] for r in db.execute("SELECT id FROM copies WHERE deleted_at='' LIMIT 5").fetchall()]

    # Simulation d'insertion de 4 brouillons
    with store.connect(write=True) as db:
        for i in range(1, 5):
            store.create_sale(
                {"title": f"Lot existant {i}", "amount_cents": 1000},
                [copies[0]],
                "tester",
                _db=db,
            )

    st = engine.status()
    assert st["active_drafts_count"] == 4
    assert st["capacity_available"] == 1

    # Rotation avec 2 nouveaux lots demandés -> total 6 > 5 -> 1 plus ancien doit être annulé
    new_lots = [
        {
            "theme": "dp_platine",
            "title": "Nouveau Lot 1",
            "count": 1,
            "total_reference_cents": 200,
            "asking_cents": 200,
            "copies": [{"id": copies[1]}],
        },
        {
            "theme": "dp_platine",
            "title": "Nouveau Lot 2",
            "count": 1,
            "total_reference_cents": 200,
            "asking_cents": 200,
            "copies": [{"id": copies[2]}],
        },
    ]

    # Dry run d'abord : aucune écriture
    dry = engine.rotate(lots_to_add=new_lots, dry_run=True)
    assert dry["dry_run"] is True
    assert len(dry["drafts_to_cancel"]) == 1
    assert dry["drafts_to_cancel"][0]["title"] == "Lot existant 1"  # Le plus ancien annulé en premier
    assert len(dry["lots_to_create"]) == 2

    # Status n'a pas bougé
    assert engine.status()["active_drafts_count"] == 4

    # Rotation réelle
    res = engine.rotate(lots_to_add=new_lots, dry_run=False)
    assert len(res["created"]) == 2
    assert len(res["drafts_to_cancel"]) == 1

    # Vérification post-rotation : 4 - 1 + 2 = 5 brouillons actifs au total !
    st_after = engine.status()
    assert st_after["active_drafts_count"] == 5
    assert st_after["capacity_available"] == 0


def test_cli_execution(test_db, tmp_path, monkeypatch):
    db_path, _ = test_db
    out_file = tmp_path / "out.json"

    monkeypatch.setattr(
        sys,
        "argv",
        ["pokeprice_lots.py", "--data", str(db_path), "--output", str(out_file), "analyze"],
    )
    main()

    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert "total_excess_duplicates" in data


def test_publish_to_storefront(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)
    from pokeprice.listings import Listings

    listings = Listings(store)

    # 1. Publier 2 cartes individuellement en vitrine
    with store.connect() as db:
        copies = [r["id"] for r in db.execute("SELECT id FROM copies WHERE identification_status='confirmed' LIMIT 2").fetchall()]

    listings.publish([copies[0]], "tester", price_cents=100)
    listings.publish([copies[1]], "tester", price_cents=100)

    # Vérifier que les 2 cartes sont en vitrine active
    with store.connect() as db:
        assert listings.active(db, copies[0]) is not None
        assert listings.active(db, copies[1]) is not None

    # 2. Créer un brouillon de vente regroupant ces 2 cartes
    with store.connect(write=True) as db:
        sale_id = store.create_sale(
            {"title": "Lot Vitrine Test", "amount_cents": 180, "asking_cents": 180},
            copies,
            "tester",
            _db=db,
        )

    # 3. Dry-run
    dry = engine.publish_to_storefront(sale_id, dry_run=True)
    assert dry["dry_run"] is True
    assert dry["unpublish_count"] == 2

    # 4. Publication réelle
    res = engine.publish_to_storefront(sale_id, dry_run=False)
    assert res["dry_run"] is False
    assert "published_listing_id" in res

    # 5. Vérifier que le lot est en ligne et que les cartes y sont rattachées
    with store.connect() as db:
        lot_listing = db.execute("SELECT * FROM listings WHERE id=?", (res["published_listing_id"],)).fetchone()
        assert lot_listing["state"] == "online"
        assert lot_listing["title"] == "Lot Vitrine Test"
        active_items = db.execute(
            "SELECT listing_id FROM listing_items WHERE active=1 AND copy_id IN (?,?)",
            (copies[0], copies[1]),
        ).fetchall()
        assert len(active_items) == 2
        assert all(it["listing_id"] == res["published_listing_id"] for it in active_items)


def test_lot_recipe_schema_validation():
    recipe = LotCompositionRecipe(
        title="Lot Pépites",
        summary="Belles cartes sous-évaluées",
        filters=HardFilters(min_condition="EX", exclude_energies=True),
        scoring=ScoringHeuristics(value_intent=ValueIntent.UNDERVALUED_GEMS),
        bundle_rules=BundleRules(target_count=5, diversity=DiversityStrategy.MAXIMIZE_SPECIES),
    )
    dumped = recipe.model_dump()
    assert dumped["title"] == "Lot Pépites"
    assert dumped["filters"]["min_condition"] == "EX"
    assert dumped["scoring"]["value_intent"] == "undervalued_gems"

    restored = LotCompositionRecipe.model_validate(dumped)
    assert restored.title == "Lot Pépites"


def test_normalize_pokemon_name():
    assert normalize_pokemon_name("Dracaufeu-EX") == "dracaufeu"
    assert normalize_pokemon_name("Pikachu VMAX") == "pikachu"
    assert normalize_pokemon_name("Lugia Légende") == "lugia"
    assert normalize_pokemon_name("Zarbi L") == "zarbi l"


def test_compose_from_recipe_undervalued_gems(test_db):
    db_path, _ = test_db
    engine = LotsEngine(db_path)

    recipe = LotCompositionRecipe(
        title="Pépites Test",
        summary="Test composition pépites",
        filters=HardFilters(min_condition="EX", max_cents=1000),
        scoring=ScoringHeuristics(value_intent=ValueIntent.UNDERVALUED_GEMS),
        bundle_rules=BundleRules(target_count=3, target_discount_percent=10),
    )

    res = engine.compose_from_recipe(recipe)
    assert "lot" in res
    assert res["lot"] is not None
    assert res["lot"]["title"] == "Pépites Test"
    assert res["lot"]["count"] <= 3
    assert res["lot"]["discount_percent"] == 10
    for c in res["lot"]["copies"]:
        assert c["reference_cents"] <= 1000


def test_compose_from_recipe_diversity_species(test_db):
    db_path, _ = test_db
    engine = LotsEngine(db_path)

    fake_pool = [
        {"id": "c1", "version": 1, "name": "Zarbi L", "catalog_id": "dp4-91", "set_name": "Diamant & Perle", "number": "91", "condition": "NM", "finish": "normal", "reference_cents": 100},
        {"id": "c2", "version": 1, "name": "Zarbi L", "catalog_id": "dp4-91", "set_name": "Diamant & Perle", "number": "91", "condition": "NM", "finish": "normal", "reference_cents": 100},
        {"id": "c3", "version": 1, "name": "Pikachu", "catalog_id": "base1-58", "set_name": "Set de Base", "number": "58", "condition": "EX", "finish": "normal", "reference_cents": 200},
    ]

    recipe = LotCompositionRecipe(
        title="Diversité Espèces",
        summary="1 carte max par espèce",
        bundle_rules=BundleRules(target_count=2, diversity=DiversityStrategy.MAXIMIZE_SPECIES),
    )

    res = engine.compose_from_recipe(recipe, duplicates=fake_pool)
    copies = res["lot"]["copies"]
    assert len(copies) == 2
    species = [normalize_pokemon_name(c["name"]) for c in copies]
    assert len(set(species)) == 2


def test_compose_from_recipe_finishes_filter(test_db):
    db_path, _ = test_db
    engine = LotsEngine(db_path)

    fake_pool = [
        {"id": "c1", "version": 1, "name": "Salamèche", "catalog_id": "base1-46", "set_name": "Set de Base", "number": "46", "condition": "NM", "finish": "normal", "reference_cents": 100},
        {"id": "c2", "version": 1, "name": "Salamèche", "catalog_id": "base1-46", "set_name": "Set de Base", "number": "46", "condition": "NM", "finish": "reverse", "reference_cents": 300},
        {"id": "c3", "version": 1, "name": "Dracaufeu", "catalog_id": "base1-4", "set_name": "Set de Base", "number": "4", "condition": "NM", "finish": "holo", "reference_cents": 5000},
    ]

    recipe = LotCompositionRecipe(
        title="Lot Reverses",
        summary="Uniquement des reverses",
        filters=HardFilters(finishes=["reverse"]),
        bundle_rules=BundleRules(target_count=5),
    )

    res = engine.compose_from_recipe(recipe, duplicates=fake_pool)
    assert res["lot"]["count"] == 1
    assert res["lot"]["copies"][0]["finish"] == "reverse"


def test_compose_cli_with_recipe_and_draft_creation(test_db, tmp_path, monkeypatch):
    db_path, store = test_db
    engine = LotsEngine(db_path)
    out_file = tmp_path / "composed_out.json"

    assert engine.status()["active_drafts_count"] == 0

    recipe_json = json.dumps({
        "title": "Lot CLI Test",
        "summary": "Créé via CLI compose",
        "filters": {"min_condition": "GD"},
        "scoring": {"value_intent": "balanced"},
        "bundle_rules": {"target_count": 2, "target_discount_percent": 15}
    })

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pokeprice_lots.py",
            "--data", str(db_path),
            "--output", str(out_file),
            "compose",
            "--recipe", recipe_json,
            "--create-draft",
        ],
    )
    main()

    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert "created_sale_id" in data
    assert data["draft_action"] == "created"
    assert data["lot"]["title"] == "Lot CLI Test"

    with store.connect() as db:
        sale = db.execute("SELECT * FROM sales WHERE id=?", (data["created_sale_id"],)).fetchone()
        assert sale is not None
        assert sale["title"] == "Lot CLI Test"
        assert sale["status"] == "draft"
        assert sale["channel"] == "Lot"


def test_compose_cli_with_mocked_prompt(test_db, tmp_path, monkeypatch):
    db_path, _ = test_db
    out_file = tmp_path / "mocked_prompt_out.json"

    import pokeprice_lots

    mocked_recipe = LotCompositionRecipe(
        title="Pépites par Prompt",
        summary="Interprété par LLM simulé",
        filters=HardFilters(min_condition="EX"),
        scoring=ScoringHeuristics(value_intent=ValueIntent.UNDERVALUED_GEMS),
        bundle_rules=BundleRules(target_count=1),
    )
    monkeypatch.setattr(pokeprice_lots, "prompt_to_recipe", lambda p: mocked_recipe)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pokeprice_lots.py",
            "--data", str(db_path),
            "--output", str(out_file),
            "compose",
            "--prompt", "trouve-moi les pépites",
            "--dry-run",
            "--create-draft",
        ],
    )
    main()

    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert data["draft_action"] == "dry_run_simulated"
    assert data["lot"]["title"] == "Pépites par Prompt"


def test_get_duplicates_pool_preserves_best_condition(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)

    # Modifier les Zarbi L pour avoir un GD en page 1 et un NM en page 8
    with store.connect(write=True) as db:
        zarbis = db.execute("SELECT id FROM copies WHERE catalog_id='dp4-91' ORDER BY page, position").fetchall()
        assert len(zarbis) >= 2
        # zarbi 0 : page 1, condition GD
        db.execute("UPDATE copies SET condition='GD', finish='non_holo', page=1, position=1 WHERE id=?", (zarbis[0][0],))
        # zarbi 1 : page 8, condition NM
        db.execute("UPDATE copies SET condition='NM', finish='non_holo', page=8, position=1 WHERE id=?", (zarbis[1][0],))


    with engine.connect() as db:
        retained, duplicates = engine.get_duplicates_pool(db)

    retained_zarbi = next(r for r in retained if r["catalog_id"] == "dp4-91")
    # La collection de Lily DOIT conserver l'exemplaire NM (meilleur état), même s'il est en page 8 !
    assert retained_zarbi["condition"] == "NM"
    assert retained_zarbi["id"] == zarbis[1][0]

    dup_ids = [d["id"] for d in duplicates if d["catalog_id"] == "dp4-91"]
    # L'exemplaire GD (page 1) doit partir dans les doublons
    assert zarbis[0][0] in dup_ids


def test_get_duplicates_pool_excludes_busy_copies(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)

    with engine.connect() as db:
        _, initial_duplicates = engine.get_duplicates_pool(db)

    initial_count = len(initial_duplicates)
    card_to_engage = initial_duplicates[0]["id"]

    # Créer un brouillon de vente engageant cette carte
    with store.connect(write=True) as db:
        store.create_sale(
            {"title": "Lot Test Réservation", "amount_cents": 500},
            [card_to_engage],
            "tester",
            _db=db,
        )

    # Vérifier que get_duplicates_pool exclut cette carte désormais engagée
    with engine.connect() as db:
        _, new_duplicates = engine.get_duplicates_pool(db)

    assert len(new_duplicates) == initial_count - 1
    assert all(d["id"] != card_to_engage for d in new_duplicates)


def test_rotation_prioritizes_invalid_zombie_drafts(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)

    with store.connect() as db:
        copies = [r["id"] for r in db.execute("SELECT id FROM copies WHERE deleted_at='' LIMIT 5").fetchall()]

    # Créer 4 brouillons
    # Brouillon 1 : Valide, plus ancien (créé en premier)
    # Brouillon 2 : Valide, intermédiaire
    # Brouillon 3 : Invalide (on va passer sa carte en 'sold' juste après)
    # Brouillon 4 : Valide, le plus récent
    draft_ids = []
    with store.connect(write=True) as db:
        for i in range(1, 5):
            sid = store.create_sale(
                {"title": f"Brouillon {i}", "amount_cents": 500},
                [copies[i-1]],
                "tester",
                _db=db,
            )
            draft_ids.append(sid)

        # Rendre le brouillon 3 invalide en marquant sa carte 'sold'
        db.execute("UPDATE copies SET stock_state='sold' WHERE id=?", (copies[2],))

    st = engine.status()
    assert st["active_drafts_count"] == 4
    # Brouillon 3 doit être détecté invalide
    b3 = next(d for d in st["active_drafts"] if d["id"] == draft_ids[2])
    assert b3["is_valid"] is False

    # Rotation avec 2 nouveaux lots -> total 6 > 5 -> 1 seul doit être annulé
    new_lots = [
        {"theme": "dp", "title": "New 1", "count": 1, "total_reference_cents": 200, "asking_cents": 200, "copies": [{"id": copies[4]}]},
        {"theme": "dp", "title": "New 2", "count": 1, "total_reference_cents": 200, "asking_cents": 200, "copies": [{"id": copies[4]}]},
    ]

    res = engine.rotate(lots_to_add=new_lots, dry_run=True)
    # Le brouillon annulé DOIT être le brouillon 3 (le zombie invalide), et PAS le brouillon 1 (plus ancien mais sain) !
    assert len(res["drafts_to_cancel"]) == 1
    cancelled = res["drafts_to_cancel"][0]
    assert cancelled["id"] == draft_ids[2]
    assert cancelled["is_valid"] is False


def test_compose_includes_photo_and_position_metadata(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)

    # Assigner une photo et une page/position au Zarbi
    with store.connect(write=True) as db:
        db.execute(
            "UPDATE copies SET photo='test_photo_zarbi.jpg', page=5, position=3 WHERE catalog_id='dp4-91'"
        )

    recipe = LotCompositionRecipe(
        title="Lot Zarbi",
        summary="Test présence photo et position",
        filters=HardFilters(pokemon_names=["Zarbi"]),
        bundle_rules=BundleRules(target_count=1),
    )

    res = engine.compose_from_recipe(recipe)
    assert res["lot"] is not None
    assert len(res["lot"]["copies"]) >= 1
    c = res["lot"]["copies"][0]
    assert c["photo"] == "test_photo_zarbi.jpg"
    assert c["page"] == 5
    assert c["position"] == 3
    assert "from_album" in c


def test_compose_stock_diagnostic_when_depleted(test_db):
    db_path, _ = test_db
    engine = LotsEngine(db_path)

    # Demander un Pokémon inexistant
    recipe = LotCompositionRecipe(
        title="Lot Introuvable",
        summary="Test diagnostic",
        filters=HardFilters(pokemon_names=["Rayquaza"]),
        bundle_rules=BundleRules(target_count=3),
    )

    res = engine.compose_from_recipe(recipe)
    assert res["lot"] is None
    assert "stock_diagnostic" in res
    diag = res["stock_diagnostic"]
    assert diag["total_in_collection"] == 0
    assert diag["available_duplicates"] == 0


def test_compose_scope_all_includes_album_copies(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)

    # Réduire le stock de Zarbi à un SEUL exemplaire (donc en album, 0 doublon)
    with store.connect(write=True) as db:
        zarbis = db.execute("SELECT id FROM copies WHERE catalog_id='dp4-91'").fetchall()
        for z in zarbis[1:]:
            db.execute("UPDATE copies SET deleted_at='2026-10-28' WHERE id=?", (z[0],))

    recipe = LotCompositionRecipe(
        title="Lot Zarbi Album",
        summary="Test scope all",
        filters=HardFilters(pokemon_names=["Zarbi"]),
        bundle_rules=BundleRules(target_count=1),
    )

    # En mode par défaut (duplicates) : 0 candidat, lot impossible
    res_dup = engine.compose_from_recipe(recipe, scope="duplicates")
    assert res_dup["candidates_count"] == 0
    assert res_dup["lot"] is None
    assert res_dup["stock_diagnostic"]["retained_for_album"] == 1
    assert res_dup["stock_diagnostic"]["available_duplicates"] == 0

    # En mode scope='all' : la carte d'album est éligible avec le drapeau from_album
    res_all = engine.compose_from_recipe(recipe, scope="all")
    assert res_all["candidates_count"] == 1
    assert res_all["lot"] is not None
    assert res_all["lot"]["contains_album_copies"] is True
    assert "album de collection" in res_all["lot"]["warning"]
    assert res_all["lot"]["copies"][0]["from_album"] is True


def test_prompt_parser_system_instruction_price_rule():
    import inspect

    from pokeprice_lots import prompt_to_recipe
    source = inspect.getsource(prompt_to_recipe)
    # Vérifier que la consigne stricte interdisant les plafonds arbitraires est bien présente
    assert "Ne JAMAIS renseigner min_cents ou max_cents sauf si un montant chiffré précis est explicité" in source
    assert "value_intent='affordable_bulk'" in source
    assert "only_trainers=True" in source


def test_compose_only_trainers(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)

    # Créer un Dresseur et un Pokémon dans les doublons
    with store.connect(write=True) as db:
        # Modifier une carte pour qu'elle devienne une Poké Ball (dresseur)
        # Exemplaire en pochette 2 : jamais celui conservé dans l'album (pochette 1)
        db.execute("UPDATE copies SET name='Poké Ball' WHERE id=(SELECT id FROM copies WHERE catalog_id='dp4-91' AND album_id='a' AND position=2)")

    recipe = LotCompositionRecipe(
        title="Lot Dresseurs",
        summary="Test only_trainers",
        filters=HardFilters(only_trainers=True),
        bundle_rules=BundleRules(target_count=1),
    )

    res = engine.compose_from_recipe(recipe)
    assert res["lot"] is not None
    assert len(res["lot"]["copies"]) >= 1
    for c in res["lot"]["copies"]:
        assert "ball" in c["name"].lower() or "dresseur" in c["name"].lower()

    # Vérifier l'absence de faux positifs sur des noms de Pokémon
    from pokeprice_lots import is_trainer
    assert is_trainer("Fantominus") is False
    assert is_trainer("Mamanbo") is False
    assert is_trainer("Medhyena de Team Aqua") is False
    assert is_trainer("Fan Club Pokémon") is True
    assert is_trainer("Lettre du Professeur") is True







# --- Publication atomique, gisement et rotation des lots en ligne -----------


def online_state(store, listing_id):
    with store.connect() as db:
        return db.execute("SELECT state FROM listings WHERE id=?", (listing_id,)).fetchone()["state"]


def draft_with_unit_listings(store, copy_ids, title="Lot vitrine"):
    """Publie chaque carte publiable seule, puis crée le brouillon qui les regroupe."""
    from pokeprice.listings import Listings

    listings = Listings(store)
    units = []
    for cid in copy_ids:
        try:
            units.append(listings.publish([cid], "tester", price_cents=100)["id"])
        except ValueError:
            pass  # carte non publiable : elle n'a pas d'annonce unitaire
    with store.connect(write=True) as db:
        sale_id = store.create_sale(
            {"title": title, "amount_cents": 300, "asking_cents": 300}, copy_ids, "tester", _db=db
        )
    return sale_id, units


def lot_listings(store):
    with store.connect() as db:
        return db.execute(
            "SELECT listing_id FROM listing_items WHERE active=1 GROUP BY listing_id HAVING count(*) > 1"
        ).fetchall()


def test_publish_refuses_an_unpublishable_card_before_any_unpublication(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)
    with store.connect() as db:
        zarbis = [r[0] for r in db.execute("SELECT id FROM copies WHERE catalog_id='dp4-91' AND language='fr'")]
        unknown = db.execute("SELECT id FROM copies WHERE identification_status!='confirmed'").fetchone()[0]
    sale_id, units = draft_with_unit_listings(store, zarbis[:2] + [unknown])
    assert len(units) == 2

    with pytest.raises(ValueError, match="aucune annonce n'a été retirée"):
        engine.publish_to_storefront(sale_id, dry_run=True)
    with pytest.raises(ValueError, match="Identité à confirmer"):
        engine.publish_to_storefront(sale_id)

    # Les annonces unitaires restent en ligne, aucun lot n'est créé, la vente est intacte.
    assert all(online_state(store, u) == "online" for u in units)
    assert lot_listings(store) == []
    with store.connect() as db:
        sale = db.execute("SELECT status, channel, version FROM sales WHERE id=?", (sale_id,)).fetchone()
    assert (sale["status"], sale["channel"], sale["version"]) == ("draft", "", 1)


def test_publish_rolls_back_unpublication_when_a_later_step_fails(test_db, monkeypatch):
    db_path, store = test_db
    engine = LotsEngine(db_path)
    with store.connect() as db:
        zarbis = [r[0] for r in db.execute("SELECT id FROM copies WHERE catalog_id='dp4-91' AND language='fr'")]
    sale_id, units = draft_with_unit_listings(store, zarbis[:2])

    def broken_update(*args, **kwargs):
        raise RuntimeError("panne simulée après la publication du lot")

    monkeypatch.setattr(engine.store(), "update_sale", broken_update)
    with pytest.raises(RuntimeError):
        engine.publish_to_storefront(sale_id)

    # La transaction unique annule dépublication et publication.
    assert all(online_state(store, u) == "online" for u in units)
    assert lot_listings(store) == []
    with store.connect() as db:
        events = db.execute("SELECT count(*) FROM events WHERE kind='unlisting'").fetchone()[0]
    assert events == 0


def test_publish_refuses_a_lot_without_price_or_already_online(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)
    with store.connect() as db:
        zarbis = [r[0] for r in db.execute("SELECT id FROM copies WHERE catalog_id='dp4-91' AND language='fr'")]
    with store.connect(write=True) as db:
        no_price = store.create_sale({"title": "Sans prix", "amount_cents": 0}, zarbis[:2], "tester", _db=db)
    with pytest.raises(ValueError, match="prix du lot"):
        engine.publish_to_storefront(no_price)

    sale_id, _ = draft_with_unit_listings(store, zarbis[1:3], title="Second lot")
    engine.publish_to_storefront(sale_id)
    with pytest.raises(ValueError, match="déjà en ligne"):
        engine.publish_to_storefront(sale_id)


def test_pool_excludes_unpriced_unconfirmed_valuable_and_reviewed_cards(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)
    unpriced = add_copy(store, "b", 4, price=None)
    unconfirmed = add_copy(store, "b", 5, price=None, identification_status="unresolved", variant_confirmed=False)
    valuable = add_copy(store, "b", 6, price=5000)
    priced = add_copy(store, "b", 7)

    with engine.connect() as db:
        pool = engine.classify_pool(db)
    dup_ids = {c["id"] for c in pool["duplicates"]}
    assert priced["id"] in dup_ids
    assert not dup_ids & {unpriced["id"], unconfirmed["id"], valuable["id"]}
    reasons = {e["id"]: e["reasons"] for e in pool["excluded"]}
    assert "price_incomplete" in reasons[unpriced["id"]]
    assert "identity_unconfirmed" in reasons[unconfirmed["id"]]
    assert "valuable_card" in reasons[valuable["id"]]
    assert "review_needed" in reasons[valuable["id"]]

    # Le rapport liste les cartes sans prix « à chiffrer », jamais dans un lot.
    report = engine.analyze()
    assert unpriced["id"] in {c["id"] for c in report["to_price"]}
    in_lots = {c["id"] for lot in report["lots"] for c in lot["copies"]}
    assert priced["id"] in in_lots
    assert not in_lots & {unpriced["id"], unconfirmed["id"], valuable["id"]}

    recipe = LotCompositionRecipe(
        title="Tous les Zarbi", summary="Test", filters=HardFilters(pokemon_names=["Zarbi"]),
        bundle_rules=BundleRules(target_count=50, diversity=DiversityStrategy.ANY),
    )
    for scope in ("duplicates", "all"):
        composed = engine.compose_from_recipe(recipe, scope=scope)
        ids = {c["id"] for c in composed["lot"]["copies"]}
        assert not ids & {unpriced["id"], unconfirmed["id"], valuable["id"]}
        assert unpriced["id"] in {c["id"] for c in composed["to_price"]}


def test_rotation_never_cancels_a_draft_whose_lot_is_online(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)
    with store.connect() as db:
        zarbis = [r[0] for r in db.execute("SELECT id FROM copies WHERE catalog_id='dp4-91' AND language='fr'")]
        others = [r[0] for r in db.execute("SELECT id FROM copies WHERE identification_status='confirmed' AND catalog_id!='dp4-91'")]
    online_sale, _ = draft_with_unit_listings(store, zarbis[:2], title="Lot en ligne")
    published = engine.publish_to_storefront(online_sale)
    with store.connect(write=True) as db:
        newer = store.create_sale({"title": "Brouillon récent", "amount_cents": 200}, [others[0]], "tester", _db=db)

    status = engine.status(max_drafts=2)
    assert status["online_drafts_count"] == 1
    new_lots = [
        {"theme": "dp", "title": f"Nouveau {i}", "count": 1, "total_reference_cents": 100,
         "asking_cents": 200, "copies": [{"id": others[1]}]}
        for i in range(2)
    ]
    dry = engine.rotate(lots_to_add=new_lots, dry_run=True, max_drafts=2)
    # Le plus ancien est en ligne : seul le brouillon récent est annulé, un seul lot entre.
    assert [d["id"] for d in dry["drafts_to_cancel"]] == [newer]
    assert [d["id"] for d in dry["online_drafts_kept"]] == [online_sale]
    assert len(dry["lots_to_create"]) == 1 and dry["lots_skipped_for_capacity"] == ["Nouveau 1"]

    res = engine.rotate(lots_to_add=new_lots, max_drafts=2)
    assert len(res["created"]) == 1
    with store.connect() as db:
        assert db.execute("SELECT status FROM sales WHERE id=?", (online_sale,)).fetchone()[0] == "draft"
        assert db.execute("SELECT status FROM sales WHERE id=?", (newer,)).fetchone()[0] == "cancelled"
    assert online_state(store, published["published_listing_id"]) == "online"
    assert engine.status(max_drafts=2)["active_drafts_count"] == 2

    # Plafond atteint par les seuls lots en ligne : aucune annulation, aucune création.
    blocked = engine.rotate(lots_to_add=new_lots, dry_run=True, max_drafts=1)
    assert [d["id"] for d in blocked["drafts_to_cancel"]] == [res["created"][0]["sale_id"]]
    assert blocked["lots_to_create"] == []


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["pokeprice_lots.py", *argv])
    main()


def test_cli_max_drafts_and_publish_all(test_db, tmp_path, monkeypatch):
    db_path, store = test_db
    out = tmp_path / "out.json"
    with store.connect() as db:
        zarbis = [r[0] for r in db.execute("SELECT id FROM copies WHERE catalog_id='dp4-91' AND language='fr'")]
        unknown = db.execute("SELECT id FROM copies WHERE identification_status!='confirmed'").fetchone()[0]
    good, units = draft_with_unit_listings(store, zarbis[:2], title="Lot publiable")
    bad, _ = draft_with_unit_listings(store, [zarbis[2], unknown], title="Lot refusé")

    run_cli(monkeypatch, "--data", str(db_path.parent), "--output", str(out), "status", "--max-drafts", "3")
    status = json.loads(out.read_text())
    assert status["max_drafts"] == 3 and status["capacity_available"] == 1

    run_cli(monkeypatch, "--data", str(db_path), "--output", str(out), "publish-to-storefront", "--all", "--dry-run")
    dry = json.loads(out.read_text())
    assert [p["sale_id"] for p in dry["published"]] == [good]
    assert lot_listings(store) == []

    run_cli(monkeypatch, "--data", str(db_path), "--output", str(out), "publish-to-storefront", "--all")
    done = json.loads(out.read_text())
    assert [p["sale_id"] for p in done["published"]] == [good]
    assert [r["sale_id"] for r in done["refused"]] == [bad]
    assert all(online_state(store, u) == "offline" for u in units)
    with store.connect() as db:
        assert db.execute(
            "SELECT state FROM listings l JOIN listing_items i ON i.listing_id=l.id WHERE i.copy_id=? AND i.active=1",
            (zarbis[2],),
        ).fetchone()["state"] == "online"

    # Un second passage ne republie pas le lot déjà en ligne.
    run_cli(monkeypatch, "--data", str(db_path), "--output", str(out), "publish-to-storefront", "--all")
    again = json.loads(out.read_text())
    assert again["published"] == [] and {s["sale_id"] for s in again["skipped"]} == {good}


def test_cli_requires_an_explicit_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, "--output", str(tmp_path / "out.json"), "status")


def test_gemini_model_comes_from_a_constant_or_the_environment(monkeypatch):
    import pokeprice_lots

    monkeypatch.delenv(pokeprice_lots.GEMINI_MODEL_ENV, raising=False)
    assert pokeprice_lots.gemini_model() == pokeprice_lots.DEFAULT_GEMINI_MODEL
    monkeypatch.setenv(pokeprice_lots.GEMINI_MODEL_ENV, "modele-de-test")
    assert pokeprice_lots.gemini_model() == "modele-de-test"


def test_get_duplicates_pool_is_defined_once():
    root = Path(__file__).resolve().parent.parent
    engine = (root / "src" / "pokeprice" / "lots" / "engine.py").read_text()
    script = (root / "scripts" / "pokeprice_lots.py").read_text()
    assert engine.count("def get_duplicates_pool(") == 1
    assert "def get_duplicates_pool(" not in script  # l'adaptateur délègue au moteur


def set_margin(store, margin):
    """What the administration's setting leaves in the base."""
    with store.connect(write=True) as db:
        db.execute("UPDATE settings SET value_json=? WHERE key='lot_max_margin'", (json.dumps(margin),))


@pytest.fixture(autouse=True)
def loosened_environment(monkeypatch):
    # The variable asks for the loosest floor in every test: nothing may follow it.
    monkeypatch.setenv("POKEPRICE_LOT_MAX_MARGIN", "50")


def test_lot_floor_follows_the_stored_margin(test_db):
    _, store = test_db
    assert lot_max_margin(store) == 15
    assert lot_floor_cents(1000, 15) == 850
    assert lot_floor_cents(333, 15) == 284  # arrondi au centime supérieur
    assert lot_floor_cents(1000, 0) == 1000
    for bad in (51, -1, 15.0, "15", True, None):
        with pytest.raises(ValueError, match="pourcentage entier"):
            lot_floor_cents(1000, bad)
    set_margin(store, 90)  # une valeur hors bornes dans la base ne desserre rien
    with pytest.raises(ValueError, match="pourcentage entier"):
        lot_max_margin(store)


def test_compose_never_discounts_below_the_floor(test_db, monkeypatch):
    db_path, _ = test_db
    engine = LotsEngine(db_path)
    assert BundleRules().target_discount_percent == 0
    recipe = LotCompositionRecipe(
        title="Lot bradé",
        summary="Décote demandée trop forte",
        bundle_rules=BundleRules(target_count=3, target_discount_percent=40),
    )
    lot = engine.compose_from_recipe(recipe)["lot"]
    assert lot["discount_percent"] == 15
    assert lot["asking_cents"] >= lot_floor_cents(lot["total_reference_cents"], 15)


def test_publish_refuses_a_lot_priced_under_the_floor(test_db, monkeypatch):
    db_path, store = test_db
    engine = LotsEngine(db_path)
    cards = [add_copy(store, "b", 10 + i, price=100)["id"] for i in range(3)]
    sale_id, units = draft_with_unit_listings(store, cards, title="Lot sous la cote")
    with store.connect(write=True) as db:
        db.execute("UPDATE sales SET amount_cents=200, asking_cents=200 WHERE id=?", (sale_id,))
    with pytest.raises(ValueError, match="plancher anti-bradage"):
        engine.publish_to_storefront(sale_id)
    with store.connect() as db:
        active = {r[0] for r in db.execute("SELECT listing_id FROM listing_items WHERE active=1")}
    assert set(units) <= active  # aucune annonce unitaire retirée

    with store.connect(write=True) as db:
        db.execute("UPDATE sales SET amount_cents=255, asking_cents=255 WHERE id=?", (sale_id,))
    engine.publish_to_storefront(sale_id)
    assert lot_listings(store)


def test_publish_refuses_a_lot_with_an_unrated_card(test_db):
    db_path, store = test_db
    engine = LotsEngine(db_path)
    rated = add_copy(store, "b", 20, price=100)["id"]
    unrated = add_copy(store, "b", 21, price=None)["id"]
    with store.connect(write=True) as db:
        sale_id = store.create_sale(
            {"title": "Lot sans cote", "amount_cents": 500, "asking_cents": 500}, [rated, unrated], "tester", _db=db
        )
    with pytest.raises(ValueError, match="sans cote"):
        engine.publish_to_storefront(sale_id)


def three_card_draft(store, first_position, price_cents):
    cards = [add_copy(store, "b", first_position + i, price=100)["id"] for i in range(3)]
    sale_id, units = draft_with_unit_listings(store, cards, title=f"Lot {first_position}")
    with store.connect(write=True) as db:
        db.execute("UPDATE sales SET amount_cents=?, asking_cents=? WHERE id=?", (price_cents, price_cents, sale_id))
    return sale_id, cards, units


@pytest.mark.parametrize("price_cents, published", [(254, False), (255, True)])
def test_publish_floor_boundary(test_db, monkeypatch, price_cents, published):
    db_path, store = test_db
    sale_id, _, _ = three_card_draft(store, 30, price_cents)
    engine = LotsEngine(db_path)
    if published:
        engine.publish_to_storefront(sale_id)
        assert lot_listings(store)
    else:
        with pytest.raises(ValueError, match="plancher anti-bradage"):
            engine.publish_to_storefront(sale_id)


def test_publish_checks_the_cotes_of_the_day(test_db, monkeypatch):
    db_path, store = test_db
    sale_id, cards, _ = three_card_draft(store, 40, 300)
    with store.connect(write=True) as db:
        db.execute(f"UPDATE copies SET reference_cents=200 WHERE id IN ({','.join('?' * len(cards))})", cards)
    with pytest.raises(ValueError, match="plancher anti-bradage"):
        LotsEngine(db_path).publish_to_storefront(sale_id)


def test_publish_all_refuses_an_undercut_lot_and_keeps_its_cards_online(test_db, monkeypatch):
    db_path, store = test_db
    sale_id, _, units = three_card_draft(store, 50, 200)
    report = LotsEngine(db_path).publish_all()
    refused = {r["sale_id"]: r["reason"] for r in report["refused"]}
    assert "plancher anti-bradage" in refused[sale_id]
    with store.connect() as db:
        active = {r[0] for r in db.execute("SELECT listing_id FROM listing_items WHERE active=1")}
    assert set(units) <= active


def test_a_zero_cote_counts_as_no_cote(test_db):
    db_path, store = test_db
    cards = [add_copy(store, "b", 60 + i, price=100)["id"] for i in range(2)]
    with store.connect(write=True) as db:
        db.execute("UPDATE copies SET reference_cents=0 WHERE id=?", (cards[0],))
        sale_id = store.create_sale({"title": "Lot à zéro", "amount_cents": 500, "asking_cents": 500}, cards, "tester", _db=db)
    with pytest.raises(ValueError, match="sans cote"):
        LotsEngine(db_path).publish_to_storefront(sale_id)


def test_compose_follows_a_stricter_margin(test_db):
    db_path, store = test_db
    set_margin(store, 0)
    recipe = LotCompositionRecipe(
        title="Lot sans décote", summary="Marge nulle",
        bundle_rules=BundleRules(target_count=3, target_discount_percent=30),
    )
    lot = LotsEngine(db_path).compose_from_recipe(recipe)["lot"]
    assert lot["discount_percent"] == 0
    assert lot["asking_cents"] >= lot["total_reference_cents"]


def test_remote_command_carries_no_margin(monkeypatch):
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr("pokeprice_lots.subprocess.run", lambda cmd, **_: calls.append(cmd) or Done())
    run_remote_command("serveur", "/srv/base", "status", [])
    assert "POKEPRICE_LOT_MAX_MARGIN" not in calls[-1][-1]
    assert "MARGIN" not in calls[-1][-1] and "marge" not in calls[-1][-1]


def test_the_lots_tool_has_no_way_to_loosen_the_floor(test_db, monkeypatch, capsys):
    import pokeprice_lots

    db_path, store = test_db
    # Ni option ni variable : l'outil ne connaît que la marge de la base.
    assert not hasattr(pokeprice_lots, "LOT_MAX_MARGIN_ENV")
    monkeypatch.setattr(sys, "argv", ["pokeprice_lots.py", "--data", str(db_path), "--output", str(db_path.parent / "o.json"), "--marge=50", "status"])
    with pytest.raises(SystemExit):
        pokeprice_lots.main()
    assert "--marge" in capsys.readouterr().err
    sale_id, _, units = three_card_draft(store, 70, 150)  # moitié de la cote : 50 % demandés par la variable
    with pytest.raises(ValueError, match="moins 15 %"):
        LotsEngine(db_path).publish_to_storefront(sale_id)
    assert not lot_listings(store)


# -- Énergies offertes (décision 0041) ------------------------------------------


def add_energy(store, position, **overrides):
    values = {"name": "Énergie Feu", "catalog_id": "", "number": "", "set_name": ""}
    return add_copy(store, "b", position, price=None, **{**values, **overrides})


@pytest.mark.parametrize("cards, asking_cents, room", [
    (3, 500, 2),    # 16 g : la lettre suivie ≤ 20 g prend encore 2 cartes
    (5, 500, 0),    # 20 g : la tranche est pleine
    (12, 500, 10),  # 34 g : 33 places sous 100 g, plafonnées à 10
    (3, 6000, 2),   # recommandé ≤ 20 g : même calcul, autre grille
])
def test_bonus_room_keeps_the_postal_tier(monkeypatch, cards, asking_cents, room):
    monkeypatch.delenv("POKEPRICE_PACKING_GRAMS", raising=False)
    monkeypatch.delenv("POKEPRICE_REGISTERED_THRESHOLD_EUR", raising=False)
    assert bonus_room(cards, asking_cents) == room


def test_lots_offer_bulk_energies_and_publish(test_db, monkeypatch):
    monkeypatch.delenv("POKEPRICE_PACKING_GRAMS", raising=False)
    db_path, store = test_db
    energies = [add_energy(store, 80 + i)["id"] for i in range(4)]
    review = add_energy(store, 90, identification_status="review", variant_confirmed=False)["id"]
    engine = LotsEngine(db_path)
    with engine.connect() as db:
        pool = [c["id"] for c in engine.bulk_bonus_pool(db)]
    assert pool == energies  # ordre du classeur ; l'énergie à revoir n'est pas en vrac
    analysis = engine.analyze()
    lot = next(l for l in analysis["lots"] if l["theme"] == "dp_platine")
    paid = [c for c in lot["copies"] if not c.get("bonus")]
    bonus = [c["id"] for c in lot["copies"] if c.get("bonus")]
    assert len(paid) == 2 and bonus == energies[:3]  # 14 g + 3 × 2 g = 20 g
    assert lot["bonus_count"] == 3 and lot["title"].endswith(" + 3 énergies offertes")
    assert lot["total_reference_cents"] == 200
    tier = lambda n: {k: shipping_quote(n, lot["asking_cents"])[k] for k in ("shipping_cents", "service")}
    assert tier(len(lot["copies"])) == tier(2)
    assert review not in pool

    created = engine.rotate(lots_to_add=[lot])["created"]
    published = engine.publish_to_storefront(created[0]["sale_id"])
    assert published["copies_count"] == 5


def test_a_lot_of_bulk_energies_alone_is_refused(test_db):
    db_path, store = test_db
    energies = [add_energy(store, 95 + i)["id"] for i in range(2)]
    with store.connect(write=True) as db:
        sale_id = store.create_sale({"title": "Vrac seul", "amount_cents": 500, "asking_cents": 500},
                                    energies, "tester", _db=db)
    with pytest.raises(ValueError, match="sans cote"):
        LotsEngine(db_path).publish_to_storefront(sale_id)
