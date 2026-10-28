import json
import sys
from pathlib import Path

import pytest
from test_library import inputs

from pokeprice.inventory import Store
from pokeprice.inventory_import import import_collection

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
    categorize_card,
    main,
    normalize_pokemon_name,
)



@pytest.fixture
def test_db(tmp_path):
    manifest = inputs(tmp_path)
    store = Store(tmp_path / "inventory")
    import_collection(store, manifest)
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
        copies = [r["id"] for r in db.execute("SELECT id FROM copies WHERE deleted_at='' LIMIT 2").fetchall()]

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
        db.execute("UPDATE copies SET name='Poké Ball' WHERE id=(SELECT id FROM copies WHERE catalog_id='dp4-91' LIMIT 1)")

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





