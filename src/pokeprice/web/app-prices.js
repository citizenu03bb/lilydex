"use strict";
// "Rare" and "Rare Holo" share the star symbol: tell what the standard print is.
function standardVariantHint(snapshot) {
  const variants = snapshot?.variants;
  if (!variants || !Object.keys(variants).length)
    return "Relevez le prix pour savoir, selon TCGdex, si la version standard de cette carte est holo ou mate.";
  const standard =
    variants.holo && !variants.normal
      ? "holo d’origine (illustration et parfois cadre brillants)"
      : variants.normal
        ? "mate"
        : "inconnue";
  const reverse = variants.reverse ? " Une reverse existe." : "";
  return `Selon TCGdex : ${snapshot.rarity || "rareté inconnue"}, version standard ${standard}.${reverse} Standard comprend les Rare Holo, Prime et LV.X d’origine. Foil correspond à une reverse ou une holo spéciale d’une édition normalement mate. Le catalogue peut être incomplet : la confirmation physique reste prioritaire.`;
}
function renderPriceSnapshot(parent, card) {
  const section = el("section", undefined, "price-panel");
  section.setAttribute("aria-label", "Relevé de prix");
  if (card.valuation) {
    const value = card.valuation;
    section.append(el("p", `Tendance : ${money(value.trend_cents)} · Prudente : ${money(value.prudent_cents)} · Estimation de vente : ${money(value.sale_estimate_cents)}`));
    const detail = el("details");
    detail.append(el("summary", "Détail du calcul"));
    detail.append(el("p", `Valeur en jeu : ${money(value.risk_cents)}${value.risk_incomplete ? " · prix incomplets" : ""} · seuil ${money(value.threshold_cents)}. Maximum prudent des variantes et éditions plausibles, sans décote d’état.`, "help"));
    if (value.manual_price)
      detail.append(el("p", `Valeur manuelle : TCGdex ne fournit pas de prix prudent, la référence saisie (${money(value.manual_price.amount_cents)}, ${value.manual_price.source}) en tient lieu. Sans moyenne à 30 jours, elle reste marquée incomplète.`, "help"));
    section.append(detail);
    if (value.bulk)
      section.append(el("p", "Énergie de base : vendue en vrac, en lot, sans cote à chercher. Elle est comptée à part dans les totaux.", "help"));
    if (card.variant_confirmed && value.variant_catalog_warning)
      section.append(el("p", "Variante confirmée physiquement ; TCGdex ne répertorie pas cette variante. La confirmation humaine est conservée.", "help"));
    if (value.market_unstable)
      section.append(el("p", "Marché instable : les moyennes divergent. Ce signal de prix ne remet pas en cause l’examen physique.", "help"));
    if (value.needs_review) {
      const reasons = el("ul", undefined, "price-warnings");
      for (const reason of value.reasons) reasons.append(el("li", reason.label));
      section.append(reasons);
    }
  }
  const snapshot = card.price_snapshot;
  const euros = (v) => (v === null || v === undefined ? "—" : money(Math.round(v * 100)));
  if (snapshot) {
    const m = snapshot.metrics;
    section.append(
      el(
        "p",
        `Dernier relevé TCGdex · ${new Date(snapshot.updated || snapshot.observed_at).toLocaleDateString("fr-FR")} · variante ${snapshot.variant}`,
        "help",
      ),
      el(
        "p",
        `Bas ${euros(m.low)} · Moyenne 30 j ${euros(m.avg30)} · Moyenne 7 j ${euros(m.avg7)} · Tendance ${euros(m.trend)}`,
      ),
    );
    if (snapshot.warnings.length) {
      const list = el("ul", undefined, "price-warnings");
      for (const warning of snapshot.warnings) {
        if (card.variant_confirmed && !card.valuation?.price_variant_issue && warning.startsWith("TCGdex ne connaît pas de version Foil")) continue;
        if (card.variant_confirmed && !card.valuation?.price_variant_issue && warning.startsWith("L’autre variante cote")) {
          list.append(el("li", warning.replace(" : une erreur de variante changerait fortement la valeur.", " · comparaison catalogue ; autre catégorie écartée après vérification physique.")));
          continue;
        }
        list.append(el("li", warning));
      }
      section.append(list);
    }
  } else
    section.append(
      el(
        "p",
        card.identification_status === "confirmed"
          ? card.catalog_id
            ? "Aucun relevé détaillé : relevez le prix pour voir le prix bas, les moyennes et les alertes."
            : "Identité confirmée sans lien TCGdex : utilisez « Identifier la carte » puis « Rechercher » avec le nom et la référence corrigés. Une référence sourcée peut aussi être saisie si le catalogue ne fournit pas de prix."
          : "Identifiez et confirmez l’édition pour relever son prix.",
        "help",
      ),
    );
  const actions = el("div", undefined, "workflow-actions");
  if (
    editAllowed() &&
    !card.deleted_at &&
    card.identification_status === "confirmed" &&
    card.catalog_id
  ) {
    const refresh = el("button", "Relever le prix (TCGdex)");
    refresh.type = "button";
    refresh.addEventListener("click", async () => {
      if (parent.elements && ["name", "set_name", "number", "language", "catalog_id", "identification_status", "stamp", "stamp_state", "distribution", "distribution_state", "finish"].some((key) => (parent.elements[key]?.value || "") !== (card[key] || ""))) {
        toast("Enregistrez d’abord les observations modifiées, puis relevez le prix.");
        return;
      }
      if (parent.elements?.foil && !parent.elements.foil.disabled && (parent.elements.foil.value === "true") !== Boolean(card.foil)) {
        toast("Enregistrez d’abord la catégorie manuelle, puis relevez le prix.");
        return;
      }
      refresh.disabled = true;
      try {
        await api(`/copies/${card.id}/price-refresh`, {
          method: "POST",
          body: JSON.stringify({ expected_version: card.version }),
        });
        await refreshSummary();
        await openDetail(card.id);
        await loadCards();
        toast("Prix relevé. La référence reste une tendance, pas un prix de vente.");
      } catch (e) {
        refresh.disabled = false;
        toast(e.message);
      }
    });
    actions.append(refresh);
  }
  if (card.cardmarket_url) {
    const link = el("a", "Voir les offres Cardmarket");
    link.href = card.cardmarket_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    actions.append(link);
    section.append(
      el(
        "p",
        card.stamp
          ? `Variante tamponnée « ${card.stamp} » : Cardmarket la range avec les Foil, mélangée aux reverses. Ne retenez que les offres dont le commentaire mentionne le tampon (« stamp »).`
          : `Filtre : langue de l’exemplaire${card.condition ? `, état ${card.condition} ou meilleur` : ""}${card.foil ? ", offres Foil uniquement" : ""}. Comparez des offres de même variante.`,
        "help",
      ),
    );
  } else if (card.cardmarket_search_url) {
    const link = el("a", "Chercher sur Cardmarket");
    link.href = card.cardmarket_search_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    actions.append(link);
    section.append(
      el(
        "p",
        "Lien déduit du nom anglais et du numéro : TCGdex ne fournit pas le produit Cardmarket. Vérifiez l’édition sur la page ouverte avant de relever la tendance.",
        "help",
      ),
    );
  }
  if (actions.children.length) section.append(actions);
  renderMarketProduct(section, card);
  renderBoundQuote(section, card);
  renderSaleEstimate(section, card);
  renderStorefront(section, card);
  parent.append(section);
}
// TCGdex may give two cards of a set one Cardmarket product (Darkrai GE 3/4).
// A person checks the page and records a verdict for this catalogue id.
function renderMarketProduct(parent, card) {
  const market = card.valuation?.market_product;
  if (!market) return;
  const box = el("div", undefined, "market-product");
  // TCGdex names are English (Airmure is Skarmory): lead with the number.
  const others = (market.shared_with || [])
    .map((o) => `n° ${o.catalog_id.split("-").at(-1)} (${o.name || "?"} en anglais${o.hp ? `, ${o.hp} PV` : ""})`)
    .join(", ");
  const own = (card.catalog_id || "").split("-").at(-1);
  if (market.verdict === "wrong")
    box.append(el("p", `Produit Cardmarket n° ${market.id_product} signalé incorrect : les prix TCGdex de cette carte sont écartés. Relevez la tendance sur la bonne page et saisissez-la comme prix de référence.`, "price-warnings"));
  else if (market.verdict === "verified")
    box.append(el("p", `Produit Cardmarket n° ${market.id_product} vérifié.`, "help"));
  else if (others)
    box.append(el("p", `TCGdex donne aussi ce produit Cardmarket à une autre carte de l’extension : ${others}. Ouvrez la page et vérifiez qu’elle montre votre n° ${own} (PV, niveau, illustration).`, "price-warnings"));
  if (editAllowed() && !card.deleted_at) {
    const details = el("details");
    details.open = Boolean(others) && !market.verdict;
    details.append(el("summary", others && !market.verdict ? "Confirmer ou rejeter ce produit Cardmarket" : "Verdict sur le produit Cardmarket"));
    // Distinct from the form's own "Motif de la modification" field below.
    const label = el("label", "Motif du verdict (obligatoire)");
    const reason = el("input");
    reason.placeholder = "Ex. page BCR 95 conforme ; ou page Lv.38, carte Lv.40";
    reason.maxLength = 1000;
    reason.addEventListener("input", () => reason.setCustomValidity(""));
    label.append(reason);
    // The box sits inside the detail form: Enter must not save the whole form.
    reason.addEventListener("keydown", (event) => {
      if (event.key === "Enter") event.preventDefault();
    });
    const error = el("p", "", "error");
    const buttons = el("div", undefined, "workflow-actions");
    const choices = [
      ["verified", "Produit vérifié", "Produit Cardmarket vérifié."],
      ["wrong", "Produit incorrect", "Produit signalé incorrect ; prix TCGdex retiré."],
      ["", "Annuler le verdict", "Verdict annulé."],
    ].filter(([verdict]) => verdict !== market.verdict && (verdict || market.verdict));
    for (const [verdict, label, done] of choices) {
      const button = el("button", label);
      button.type = "button";
      button.addEventListener("click", async () => {
        if (!reason.value.trim()) {
          // Not `required`: an empty verdict box must not block the main form.
          reason.setCustomValidity("Indiquez le motif du verdict.");
          reason.reportValidity();
          reason.focus();
          return;
        }
        button.disabled = true;
        error.textContent = "";
        try {
          await api(`/copies/${card.id}/market-product`, {
            method: "POST",
            body: JSON.stringify({ expected_version: card.version, verdict, reason: reason.value.trim() }),
          });
          await refreshSummary();
          await openDetail(card.id);
          await loadCards();
          toast(done);
        } catch (e) {
          button.disabled = false;
          error.textContent = e.message;
        }
      });
      buttons.append(button);
    }
    details.append(label, buttons, error);
    box.append(details);
  }
  parent.append(box);
}
// A proven market binding: the metrics of its family are read together on the
// product page and recorded as one acquisition (trend and 30-day average).
function renderBoundQuote(parent, card) {
  const binding = card.reference_binding;
  if (!binding || !editAllowed() || card.deleted_at) return;
  const labels = { trend: "Tendance des prix", avg30: "Prix moyen 30 jours" };
  const box = el("div", undefined, "bound-quote");
  const details = el("details");
  details.append(
    el("summary", "Saisir un relevé Cardmarket lié au référentiel"),
    el("p", `Produit ${binding.product_ref.split(":")[1]}, filtres ${Object.entries(binding.filters).map(([k, v]) => `${k}=${v}`).join(", ")}. Ouvrez « Voir les offres Cardmarket » et recopiez le cadre Info de cette page, toutes les valeurs ensemble.`, "help"),
  );
  const inputs = {};
  // Same order as Cardmarket's Info box: the trend comes before the averages.
  const order = ["trend", "avg30"];
  const metrics = Object.keys(binding.metric_family.metrics).sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99) || a.localeCompare(b));
  for (const metric of metrics) {
    const label = el("label", `${labels[metric] || metric} (€)`);
    const input = el("input");
    input.type = "number";
    input.min = "0";
    input.step = "0.01";
    label.append(input);
    inputs[metric] = input;
    details.append(label);
  }
  const dayLabel = el("label", "Date du relevé");
  const day = el("input");
  day.type = "date";
  day.value = new Date().toISOString().slice(0, 10);
  dayLabel.append(day);
  const captureLabel = el("label", "Empreinte de la capture archivée (facultatif)");
  const capture = el("input");
  capture.placeholder = "SHA-256 donné par reference-archive";
  captureLabel.append(capture);
  const reasonLabel = el("label", "Motif (obligatoire)");
  const reason = el("input");
  reason.maxLength = 1000;
  reasonLabel.append(reason);
  // Inside the detail form: no `required`, and Enter must not save the whole form.
  for (const input of [...Object.values(inputs), day, capture, reason])
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") event.preventDefault(); });
  const run = el("button", "Enregistrer le relevé lié");
  run.type = "button";
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  run.addEventListener("click", async () => {
    const missing = Object.values(inputs).find((input) => input.value === "");
    if (missing || !reason.value.trim() || !day.value) {
      error.textContent = "Saisissez toutes les valeurs, la date et le motif.";
      return;
    }
    run.disabled = true;
    error.textContent = "";
    try {
      await api(`/copies/${card.id}/bound-quote`, {
        method: "POST",
        body: JSON.stringify({
          expected_version: card.version,
          metrics: Object.fromEntries(Object.entries(inputs).map(([k, input]) => [k, input.value])),
          observed_on: day.value,
          capture_sha256: capture.value.trim(),
          reason: reason.value.trim(),
        }),
      });
      await refreshSummary();
      await openDetail(card.id);
      await loadCards();
      toast("Relevé lié enregistré.");
    } catch (e) {
      run.disabled = false;
      error.textContent = e.message;
    }
  });
  details.append(dayLabel, captureLabel, reasonLabel, run, error);
  box.append(details);
  parent.append(box);
}
// Asking prices pasted from Cardmarket: the server parses them and applies a
// fixed rule (same condition first, else a documented per-step discount).
function renderSaleEstimate(parent, card) {
  const box = el("div", undefined, "sale-estimate");
  const estimate = card.sale_estimate;
  if (estimate) {
    if (card.sale_estimate_stale)
      box.append(el("p", "Estimation ancienne : l’identité, la variante ou l’état a changé. Elle est exclue des totaux ; collez de nouvelles offres pour la refaire.", "price-warnings"));
    box.append(
      el(
        "p",
        `Estimation de vente : ${money(Math.round(estimate.estimate_eur * 100))} (${money(Math.round(estimate.low_eur * 100))} – ${money(Math.round(estimate.high_eur * 100))}) · confiance ${estimate.confidence} · ${estimate.offers_used} offre(s) retenue(s) sur ${estimate.offers_total} · le ${new Date(estimate.observed_at).toLocaleDateString("fr-FR")}`,
        "sale-estimate-value",
      ),
      el("p", estimate.method, "help"),
    );
    if (estimate.warnings.length) {
      const list = el("ul", undefined, "price-warnings");
      for (const warning of estimate.warnings) list.append(el("li", warning));
      box.append(list);
    }
  }
  if (editAllowed() && !card.deleted_at) {
    const details = el("details");
    details.append(
      el(
        "summary",
        estimate ? "Refaire l’estimation avec de nouvelles offres" : "Estimer le prix de vente depuis Cardmarket",
      ),
      el(
        "p",
        "Ouvrez « Voir les offres Cardmarket », sélectionnez toute la page (Ctrl+A), copiez (Ctrl+C) et collez ici. Ce sont des prix demandés, pas des ventes : comptez aussi les frais et le port.",
        "help",
      ),
    );
    const text = el("textarea");
    text.rows = 4;
    text.setAttribute("aria-label", "Offres copiées depuis Cardmarket");
    const run = el("button", "Estimer");
    run.type = "button";
    const error = el("p", "", "error");
    error.setAttribute("role", "alert");
    run.addEventListener("click", async () => {
      if (!text.value.trim()) return;
      run.disabled = true;
      error.textContent = "";
      try {
        await api(`/copies/${card.id}/sale-estimate`, {
          method: "POST",
          body: JSON.stringify({ text: text.value }),
        });
        await openDetail(card.id);
      } catch (e) {
        error.textContent = e.message;
        run.disabled = false;
      }
    });
    details.append(text, run, error);
    box.append(details);
  }
  if (box.children.length) parent.append(box);
}
