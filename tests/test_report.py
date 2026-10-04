import pandas as pd
import pytest
from pokeprice.report import detect_card_anomaly, apply_pricing_and_anomalies, CONDITION_MULTIPLIERS


def test_condition_multipliers():
    assert CONDITION_MULTIPLIERS["NM"] == 1.0
    assert CONDITION_MULTIPLIERS["EX"] == 0.85
    assert CONDITION_MULTIPLIERS["GD"] == 0.70
    assert CONDITION_MULTIPLIERS["LP"] == 0.55
    assert CONDITION_MULTIPLIERS["PL"] == 0.40
    assert CONDITION_MULTIPLIERS["PO"] == 0.15


def test_detect_counterfeit_risk_base_set_non_holo():
    # Base set 6/102 (Léviator) non-holo should trigger anomaly
    row = {
        "Identified_Name": "Léviator",
        "Extension": "Set de Base",
        "Numero_Officiel": "6/102",
        "Is_Foil": "Non"
    }
    warning = detect_card_anomaly(row)
    assert warning != ""
    assert "Incohérence Holo" in warning

    # Base set 6/102 holo should NOT trigger anomaly
    row_holo = {
        "Identified_Name": "Léviator",
        "Extension": "Set de Base",
        "Numero_Officiel": "6/102",
        "Is_Foil": "Oui"
    }
    assert detect_card_anomaly(row_holo) == ""


def test_apply_pricing_and_anomalies():
    data = [
        {
            "Page": 1, "Position": 1, "Identified_Name": "Pikachu", "Extension": "EX Fantômes Holon",
            "Numero_Officiel": "78/110", "Is_Foil": "Oui", "Etat": "PO", "Prix_Estime_EUR": 100.0
        },
        {
            "Page": 1, "Position": 2, "Identified_Name": "Léviator", "Extension": "Set de Base",
            "Numero_Officiel": "6/102", "Is_Foil": "Non", "Etat": "LP", "Prix_Estime_EUR": 20.0
        },
        {
            "Page": 1, "Position": 3, "Identified_Name": "Dracaufeu", "Extension": "Set de Base",
            "Numero_Officiel": "4/102", "Is_Foil": "Oui", "Etat": "NM", "Prix_Estime_EUR": 250.0
        }
    ]
    df = pd.DataFrame(data)
    df_res = apply_pricing_and_anomalies(df)

    # Pikachu PO -> 100 * 0.15 = 15.00
    assert df_res.loc[0, "Prix_Ajuste_EUR"] == 15.0
    assert df_res.loc[0, "Est_Suspecte"] == "Non"

    # Léviator non-holo Base Set -> suspect -> prix ajusté 0.0
    assert df_res.loc[1, "Est_Suspecte"] == "Oui"
    assert df_res.loc[1, "Prix_Ajuste_EUR"] == 0.0

    # Dracaufeu NM -> 250 * 1.0 = 250.0
    assert df_res.loc[2, "Prix_Ajuste_EUR"] == 250.0
    assert df_res.loc[2, "Est_Suspecte"] == "Non"
