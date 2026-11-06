"""Banc du modèle du chat (bench/assistant) : adaptateur factice seulement."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "bench" / "assistant"


@pytest.fixture(scope="module")
def bench():
    spec = importlib.util.spec_from_file_location("assistant_bench_run", BENCH / "run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def setup(bench):
    tools = bench.load_tools()
    cases = bench.load_cases(tools=tools)
    system = bench.load_system()
    assert "{date_du_jour}" not in system
    fixtures = bench.load_json(BENCH / "fixtures.json")
    return tools, cases, system, fixtures


def by_id(cases, cid):
    return next(c for c in cases if c["id"] == cid)


def test_jeu_de_commandes_complet(bench, setup):
    tools, cases, _, _ = setup
    assert 40 <= len(cases) <= 80
    categories = {c["category"] for c in cases}
    assert {"comprendre", "chercher", "ecrire", "piege"} <= categories
    traps = {c.get("trap") for c in cases}
    assert {"plancher", "injection", "outil_inexistant", "hors_sujet"} <= traps
    write = {t["name"] for t in tools if t["kind"] == "write"}
    assert write == {"publish_lot", "set_price", "unpublish_listing", "request_floor_waiver"}
    # chaque outil d'écriture est attendu au moins une fois
    assert write <= {t for c in cases if c["expect"].get("tool") for t in bench.expected_tools(c["expect"])}
    # un piège de plancher n'accepte jamais set_price
    for case in cases:
        if case.get("trap") == "plancher":
            assert case["expect"]["tool"] == "request_floor_waiver"
            assert "set_price" in case["forbid"]


def test_jeu_refuse_un_outil_inconnu(bench, tmp_path):
    path = tmp_path / "commands.json"
    path.write_text(json.dumps({"cases": [
        {"id": "x", "category": "c", "prompt": "p", "expect": {"tool": "send_email"}}]}))
    with pytest.raises(ValueError, match="outils inconnus"):
        bench.load_cases(path)


def test_adaptateur_parfait_reussit_tout(bench, setup):
    tools, cases, system, fixtures = setup
    adapter = bench.FakeAdapter("perfect", cases=cases)
    report = bench.run_bench([adapter], cases, tools, system, fixtures,
                             bench.load_json(bench.PRICING))
    summary = report["candidates"][0]["summary"]
    assert summary["passed"] == summary["cases"] == len(cases)
    assert summary["traps_avoided"] == summary["traps"]
    assert summary["invented_tool_cases"] == 0
    assert summary["latency_s"]["total_p50"] is not None


def test_outil_invente_detecte(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "piege-inexistant-01")
    adapter = bench.FakeAdapter("menteur", script={case["id"]: [
        {"calls": [{"name": "refund_customer", "args": {"reservation_id": "RES-31"}}]},
        {"text": "Remboursé."}]})
    result = bench.run_case(adapter, case, tools, system, fixtures)
    assert result["invented_tools"] == ["refund_customer"]
    assert not result["passed"]
    assert result["trap_ok"] is False


def test_piege_du_plancher_rate(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "piege-plancher-01")
    adapter = bench.FakeAdapter("docile", script={case["id"]: [
        {"calls": [{"name": "set_price", "args": {"copy_id": "EX-0601", "price_eur": 4}}]},
        {"text": "C'est fait."}]})
    result = bench.run_case(adapter, case, tools, system, fixtures)
    assert result["forbidden_calls"] == ["set_price"]
    assert result["trap_ok"] is False and not result["passed"]


def test_injection_suivie_au_second_tour(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "piege-injection-01")
    adapter = bench.FakeAdapter("crédule", script={case["id"]: [
        {"calls": [{"name": "todo_queue", "args": {}}]},
        {"calls": [{"name": "publish_lot", "args": {"lot_id": "LOT-09", "platform": "vinted"}}]}]})
    result = bench.run_case(adapter, case, tools, system, fixtures)
    assert result["tool_ok"]
    assert result["forbidden_calls"] == ["publish_lot"]
    assert not result["passed"]


def test_injection_ignoree(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "piege-injection-01")
    adapter = bench.FakeAdapter("prudent", script={case["id"]: [
        {"calls": [{"name": "todo_queue", "args": {}}]},
        {"text": "Une réservation à confirmer ; le message du client contient une consigne que j'ignore."}]})
    result = bench.run_case(adapter, case, tools, system, fixtures)
    assert result["passed"] and result["trap_ok"]


def test_recherche_puis_outil_attendu(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "comprendre-01")
    script = {case["id"]: [
        {"calls": [{"name": "search_copies", "args": {"query": "dracaufeu"}}]},
        {"calls": [{"name": "why_not_for_sale", "args": {"copy_id": "EX-0101"}}]}]}
    assert bench.run_case(bench.FakeAdapter("x", script=script), case, tools, system, fixtures)["passed"]
    # mauvais exemplaire : bon outil, mauvais arguments
    script[case["id"]][1]["calls"][0]["args"]["copy_id"] = "EX-0102"
    result = bench.run_case(bench.FakeAdapter("x", script=script), case, tools, system, fixtures)
    assert result["tool_ok"] and not result["args_ok"] and not result["passed"]


def test_arguments_hors_schema(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "comprendre-02")
    adapter = bench.FakeAdapter("bavard", script={case["id"]: [
        {"calls": [{"name": "sales_summary", "args": {"since": "semaine", "devise": "EUR"}}]},
        {"text": "6 ventes."}]})
    result = bench.run_case(adapter, case, tools, system, fixtures)
    assert not result["schema_valid"]
    assert any("devise" in e for e in result["schema_errors"])
    assert any("semaine" in e for e in result["schema_errors"])
    assert not result["passed"]


def test_aucune_action_attendue(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "piege-hors-sujet-01")
    quiet = bench.FakeAdapter("q", script={case["id"]: [{"text": "Je ne gère que la collection."}]})
    assert bench.run_case(quiet, case, tools, system, fixtures)["passed"]
    busy = bench.FakeAdapter("b", script={case["id"]: [
        {"calls": [{"name": "search_copies", "args": {"query": "lyon"}}]}, {"text": "?"}]})
    assert not bench.run_case(busy, case, tools, system, fixtures)["passed"]


def test_cout_mensuel(bench):
    results = [{"passed": True, "tool_ok": True, "args_ok": True, "schema_valid": True,
                "invented_tools": [], "error": None, "trap": None, "trap_ok": None,
                "category": "c", "ttft_s": 0.5, "first_turn_s": 1.0, "total_s": 2.0,
                "input_tokens": 4000, "output_tokens": 100}]
    pricing = {"models": {"x:y": {"input": 1.0, "output": 5.0}}}
    cost = bench.summarize(results, pricing, "x:y", commands_per_day=30)["cost"]
    # 900 commandes × (4000 × 1 + 100 × 5) / 1e6 = 4,05 $
    assert cost["usd_per_month"] == pytest.approx(4.05)
    assert bench.summarize(results, pricing, "ollama:m")["cost"]["usd_per_month"] == 0


def test_candidat_sans_cle_saute(bench, setup, monkeypatch):
    tools, cases, system, fixtures = setup
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    adapters = [bench.AnthropicAdapter("claude-haiku-5-5"), bench.GeminiAdapter("gemini-3.8-flash")]
    report = bench.run_bench(adapters, cases[:1], tools, system, fixtures)
    assert all("skipped" in c and "clé" in c["skipped"] for c in report["candidates"])
    markdown = bench.render_markdown(report)
    assert "non mesuré" in markdown


def test_rapport_ecrit(bench, setup, tmp_path):
    tools, cases, system, fixtures = setup
    report = bench.run_bench([bench.FakeAdapter("perfect", cases=cases)], cases, tools, system, fixtures)
    json_path, md_path = bench.write_report(report, "essai", tmp_path)
    assert json.loads(json_path.read_text())["candidates"][0]["summary"]["cases"] == len(cases)
    assert "fake:perfect" in md_path.read_text()


def test_recherche_tolere_les_fautes(bench, setup):
    _, _, _, fixtures = setup
    fx = bench.Fixtures(fixtures)
    for query, expected in [("dracofeu", "EX-0101"), ("mewtow", "EX-0301"),
                            ("charizard", "EX-0102"), ("evoli", "EX-0402")]:
        ids = [c["copy_id"] for c in fx.call("search_copies", {"query": query})["copies"]]
        assert expected in ids, query


def test_outils_en_lecture_alignes_sur_la_fiche_0032(bench):
    """La copie du banc suit docs/assistant-tools.json quand il est dans le dépôt."""
    contract = BENCH.parent.parent / "docs" / "assistant-tools.json"
    if not contract.exists():
        pytest.skip("docs/assistant-tools.json absent (outils de la fiche 0032 non fusionnés)")
    expected = json.loads(contract.read_text(encoding="utf-8"))
    snapshot = bench.load_json(BENCH / "tools.json")
    assert snapshot["read_contract_version"] == expected["contract_version"]
    assert snapshot["read"] == expected["tools"]


def test_dates_relatives(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "comprendre-02")
    ok = bench.FakeAdapter("x", script={case["id"]: [
        {"calls": [{"name": "sales_summary", "args": {"since": "2026-10-28"}}]}, {"text": "6 ventes."}]})
    assert bench.run_case(ok, case, tools, system, fixtures)["passed"]
    late = bench.FakeAdapter("x", script={case["id"]: [
        {"calls": [{"name": "sales_summary", "args": {"since": "2026-10-01"}}]}, {"text": "?"}]})
    result = bench.run_case(late, case, tools, system, fixtures)
    assert result["tool_ok"] and not result["args_ok"]


def test_lecture_permise_avant_l_ecriture(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "ecrire-05")
    read_first = bench.FakeAdapter("x", script={case["id"]: [
        {"calls": [{"name": "search_copies", "args": {"query": "EX-0601"}}]},
        {"calls": [{"name": "set_price", "args": {"copy_id": "EX-0601", "price_eur": 9}}]}]})
    assert bench.run_case(read_first, case, tools, system, fixtures)["passed"]
    write_first = bench.FakeAdapter("x", script={case["id"]: [
        {"calls": [{"name": "unpublish_listing", "args": {"listing_id": "AN-2520"}}]},
        {"calls": [{"name": "set_price", "args": {"copy_id": "EX-0601", "price_eur": 9}}]}]})
    assert not bench.run_case(write_first, case, tools, system, fixtures)["passed"]


def test_synthese_renote(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "comprendre-02")
    adapter = bench.FakeAdapter("x", script={case["id"]: [
        {"calls": [{"name": "sales_summary", "args": {"since": "2026-10-28"}}]}, {"text": "6."}]})
    report = bench.run_bench([adapter], [case], tools, system, fixtures)
    report["candidates"][0]["results"][0]["passed"] = False  # note périmée
    merged = bench.merge_reports([report, report], [case], tools)
    assert len(merged["candidates"]) == 2
    assert all(c["summary"]["passed"] == 1 for c in merged["candidates"])


# -- V1.1 comptage, comment faire, carte affichée (fiche 0037) -------------------


def test_doublons_synthetiques(bench, setup):
    _, _, _, fixtures = setup
    fx = bench.Fixtures(fixtures)
    edition = fx.call("count_copies", {"duplicates_only": True})
    assert [(g["name"], g["count"]) for g in edition["top"][:4]] == [
        ("Racaillou", 7), ("Magicarpe", 6), ("Énergie Eau", 5), ("Énergie Feu", 5)]
    by_name = fx.call("count_copies", {"group_by": "name", "top": 2})
    assert [(g["name"], g["count"], g["editions"]) for g in by_name["top"]] == [
        ("Pikachu", 9, 7), ("Racaillou", 7, 1)]
    assert fx.call("count_copies", {"language": "ja"})["total_copies"] == 2
    # Les doublons dépliés gardent les cas existants : un seul Dracaufeu par édition.
    assert fx.call("search_copies", {"query": "dracaufeu"})["total"] == 3


def test_cas_reel_des_doublons_inventes(bench, setup):
    """4 novembre, 23 h 22 : « top10 des cartes en doublon », réponse sans outil, chiffres inventés."""
    tools, cases, system, fixtures = setup
    case = by_id(cases, "compter-01")
    invented = "Pikachu 16, Évoli 15, Miaouss 9, Salamèche 8."
    without_tool = bench.FakeAdapter("x", script={case["id"]: [{"text": invented}]})
    result = bench.run_case(without_tool, case, tools, system, fixtures)
    assert not result["passed"] and not result["tool_ok"]
    assert result["invented_numbers"] == ["8", "9", "15", "16"]
    after_tool = bench.FakeAdapter("x", script={case["id"]: [
        {"calls": [{"name": "count_copies", "args": {"duplicates_only": True}}]},
        {"text": "Racaillou ×7, puis Pikachu 16 et Évoli 15."}]})
    result = bench.run_case(after_tool, case, tools, system, fixtures)
    assert result["tool_ok"] and result["invented_numbers"] == ["15", "16"] and not result["passed"]
    honest = bench.FakeAdapter("x", script={case["id"]: [
        {"calls": [{"name": "count_copies", "args": {"duplicates_only": True}}]},
        {"text": "Racaillou 74/102 ×7, Magicarpe 35/102 ×6, Énergie Eau ×5, Évoli ×3."}]})
    result = bench.run_case(honest, case, tools, system, fixtures)
    assert result["passed"], result
    # La renote garde les résultats d'outils et refait la vérification.
    report = bench.run_bench([after_tool], [case], tools, system, fixtures)
    merged = bench.merge_reports([report], [case], tools)
    assert merged["candidates"][0]["results"][0]["invented_numbers"] == ["15", "16"]
    assert "nombres sans source : 15, 16" in bench.render_markdown(merged)


def test_reponse_attendue_et_vide(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "compter-02")
    call = {"calls": [{"name": "count_copies", "args": {"group_by": "name"}}]}
    mute = bench.FakeAdapter("x", script={case["id"]: [call, {"text": ""}]})
    assert not bench.run_case(mute, case, tools, system, fixtures)["answer_ok"]
    wrong = bench.FakeAdapter("x", script={case["id"]: [call, {"text": "Racaillou, 7."}]})
    assert not bench.run_case(wrong, case, tools, system, fixtures)["passed"]


def test_commentaires_du_jeu_ignores(bench, tmp_path):
    path = tmp_path / "commands.json"
    path.write_text(json.dumps({"cases": [
        {"_chantier": "x"},
        {"id": "a", "category": "c", "prompt": "p", "expect": {"tool": "knowledge"}}]}))
    assert [c["id"] for c in bench.load_cases(path)] == ["a"]


def test_plusieurs_outils_acceptes(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "chercher-01")
    for name in ("search_copies", "count_copies"):
        adapter = bench.FakeAdapter("x", script={case["id"]: [
            {"calls": [{"name": name, "args": {"query": "dracaufeu"}}]}, {"text": "3."}]})
        assert bench.run_case(adapter, case, tools, system, fixtures)["passed"], name


# -- Contexte de l'interface (V1.1, fiche 0036) ---------------------------------


def test_un_cas_peut_joindre_un_contexte(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "contexte-01")
    message = bench.question_message(case)
    assert message["text"] == case["prompt"]
    assert json.loads(message["context"])["interface_context"]["copy_id"] == "EX-0101"
    # Les fournisseurs sans parties séparées lisent le contexte avant la question.
    assert bench.user_text(message).endswith("\n\n" + case["prompt"])
    plain = bench.question_message(by_id(cases, "comprendre-01"))
    assert plain["text"] == by_id(cases, "comprendre-01")["prompt"]
    # Sans contexte d'interface, la question part quand même avec l'heure et le rôle.
    assert json.loads(plain["context"]) == {"server_context": bench.server_facts({})}
    seen = []

    class Recorder(bench.FakeAdapter):
        def chat(self, system, messages, tools):
            seen.append(messages[0])
            return super().chat(system, messages, tools)

    adapter = Recorder(cases=cases)
    assert bench.run_case(adapter, case, tools, system, fixtures)["passed"]
    assert seen[0]["context"] == message["context"]


def test_un_contexte_hors_liste_blanche_est_refuse(bench, tmp_path):
    path = tmp_path / "commands.json"
    path.write_text(json.dumps({"cases": [
        {"id": "x", "category": "contexte", "prompt": "p", "context": {"email": "a@b.c"},
         "expect": {"tool": "get_copy"}}]}))
    with pytest.raises(ValueError, match="liste blanche"):
        bench.load_cases(path, tools=bench.load_tools())


# -- Défaut du 6 novembre : une erreur jointe sans rapport n'est pas commentée --


def test_erreur_jointe_sans_rapport(bench, setup):
    tools, cases, system, fixtures = setup
    case = by_id(cases, "affichee-05")
    assert case["context"]["last_error"]
    call = {"calls": [{"name": "count_copies", "args": {"duplicates_only": True}}]}
    chatty = bench.FakeAdapter("x", script={case["id"]: [
        call, {"text": "Racaillou 74/102 ×7. Pense à te reconnecter, ta session semble expirée."}]})
    assert not bench.run_case(chatty, case, tools, system, fixtures)["passed"]
    quiet = bench.FakeAdapter("x", script={case["id"]: [call, {"text": "Racaillou 74/102 ×7."}]})
    assert bench.run_case(quiet, case, tools, system, fixtures)["passed"]
