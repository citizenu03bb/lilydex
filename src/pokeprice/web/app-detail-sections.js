"use strict";
// Storefront publication: the computed price, or why the card cannot go alone.
function renderStorefront(parent, card) {
  const box = el("div", undefined, "storefront");
  box.append(el("p", "Vitrine : chargement…", "help"));
  parent.append(box);
  const publish = async (body) => {
    await api(`/copies/${card.id}/listing`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    await openDetail(card.id);
  };
  api(`/copies/${card.id}/listing`)
    .then(({ listing, proposal }) => {
      box.replaceChildren();
      const error = el("p", "", "error");
      error.setAttribute("role", "alert");
      const guarded = (action) => async () => {
        error.textContent = "";
        try {
          await action();
        } catch (e) {
          error.textContent = e.message;
        }
      };
      const lot = listing && listing.items.length > 1;
      if (listing && listing.state === "online") {
        box.append(
          el(
            "p",
            `En vitrine à ${money(listing.price_cents)}` +
              (lot ? ` (lot de ${listing.items.length} cartes)` : "") +
              ` · ${listing.price_source}` +
              (listing.available ? "" : " · hors vitrine : un exemplaire est réservé, vendu ou supprimé"),
            "storefront-value",
          ),
        );
        if (editAllowed()) {
          const remove = el("button", lot ? "Retirer le lot de la vitrine" : "Retirer de la vitrine");
          remove.type = "button";
          remove.addEventListener(
            "click",
            guarded(async () => {
              await api(`/copies/${card.id}/listing`, { method: "DELETE" });
              await openDetail(card.id);
            }),
          );
          box.append(remove);
        }
      } else if (proposal.publishable) {
        box.append(
          el("p", `Prix de vitrine proposé : ${money(proposal.price_cents)} · ${proposal.source}`, "storefront-value"),
        );
        if (editAllowed()) {
          const go = el("button", "Publier à ce prix");
          go.type = "button";
          go.addEventListener("click", guarded(() => publish({})));
          box.append(go);
        }
      } else {
        box.append(el("p", "Pas de prix de vitrine automatique :", "help"));
        const list = el("ul", undefined, "price-warnings");
        for (const reason of proposal.reasons) list.append(el("li", reason));
        box.append(list);
      }
      if (editAllowed() && !lot && card.stock_state === "available" && !card.deleted_at) {
        const baseFloor = selectionFloor([card]);
        const cardFloor = {
          ...baseFloor,
          floorCents: proposal.floor_cents ?? baseFloor.floorCents,
        };
        const details = el("details");
        details.append(
          el(
            "summary",
            listing?.state === "online"
              ? "Changer le prix de vitrine"
              : "Publier à un prix fixé à la main",
          ),
          el("p", selectionFloorLabel(cardFloor), "help"),
        );
        const amount = el("input");
        amount.type = "number";
        amount.min = (cardFloor.floorCents / 100).toFixed(2);
        amount.step = "0.01";
        amount.setAttribute("aria-label", "Prix de vitrine en euros");
        const go = el("button", "Publier à ce prix");
        go.type = "button";
        go.addEventListener(
          "click",
          guarded(async () => {
            if (!amount.value) return;
            const cents = Math.round(
              Number(String(amount.value).replace(",", ".")) * 100,
            );
            if (!Number.isFinite(cents) || cents < cardFloor.floorCents) {
              throw new Error(
                selectionFloorRefusal(
                  Number.isFinite(cents) ? cents : 0,
                  cardFloor,
                ),
              );
            }
            await publish({ price_eur: amount.value });
          }),
        );
        details.append(amount, go);
        box.append(details);
      }
      box.append(error);
    })
    .catch((e) => box.replaceChildren(el("p", e.message, "error")));
}
function renderCopyRemoval(parent, card) {
  if (state.user?.role !== "admin") return;
  const restoring = Boolean(card.deleted_at);
  const section = el("section", undefined, "condition-panel");
  section.setAttribute(
    "aria-label",
    restoring ? "Restaurer l’exemplaire" : "Supprimer l’exemplaire",
  );
  const action = el(
    "button",
    restoring ? "Restaurer cet exemplaire" : "Supprimer cet exemplaire",
  );
  action.type = "button";
  action.disabled = !restoring && card.stock_state !== "available";
  section.append(action);
  const confirmation = el("form");
  confirmation.hidden = true;
  confirmation.append(el("p", cardLocation(card)));
  confirmation.append(
    el(
      "p",
      restoring
        ? "Cet exemplaire retrouvera sa place dans la collection."
        : "Cet exemplaire sera placé dans la corbeille. Ses photos et son historique seront conservés. Vous pourrez le restaurer depuis le filtre Stock → Corbeille.",
      "help",
    ),
  );
  const label = el(
    "label",
    restoring ? "Motif de la restauration" : "Motif de la suppression",
  );
  const reason = el("input");
  reason.required = true;
  reason.maxLength = 1000;
  label.append(reason);
  const confirm = el(
    "button",
    restoring ? "Confirmer la restauration" : "Confirmer la suppression",
    "primary",
  );
  confirm.type = "submit";
  const cancel = el("button", "Annuler");
  cancel.type = "button";
  cancel.addEventListener("click", () => {
    confirmation.hidden = true;
    action.hidden = false;
  });
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  confirmation.append(label, confirm, cancel, error);
  action.addEventListener("click", () => {
    action.hidden = true;
    confirmation.hidden = false;
    reason.focus();
  });
  confirmation.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (confirm.disabled) return;
    confirm.disabled = true;
    error.textContent = "";
    try {
      await api(`/copies/${card.id}${restoring ? "/restore" : ""}`, {
        method: restoring ? "POST" : "DELETE",
        body: JSON.stringify({
          expected_version: card.version,
          reason: reason.value,
        }),
      });
      state.selected.delete(card.id);
      selectionBar();
      $("detail-dialog").close();
      await refreshSummary();
      await loadCards();
      toast(
        restoring
          ? "Exemplaire restauré."
          : "Exemplaire placé dans la corbeille.",
      );
    } catch (e) {
      error.textContent = e.message;
    } finally {
      confirm.disabled = false;
    }
  });
  section.append(confirmation);
  parent.append(section);
}
function renderConditionAssessment(parent, card, previous = null) {
  const panel = el("section", undefined, "condition-panel");
  panel.setAttribute("aria-label", "Aide à l’évaluation de l’état");
  panel.append(el("h3", "Aide à l’évaluation de l’état"));
  panel.append(
    el(
      "p",
      `État enregistré : ${card.condition || "inconnu"} · ${card.condition_confirmed ? "vérifié sur la carte" : "à confirmer"}`,
    ),
  );
  const status = el("p", "", "help");
  status.setAttribute("role", "status");
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  if (editAllowed()) {
    panel.append(
      el(
        "p",
        "Cette action transmet les photos entières disponibles à Gemini. La proposition ne modifie ni l’état enregistré ni le prix.",
        "help",
      ),
    );
    const evaluate = el("button", "Évaluer l’état", "primary");
    evaluate.type = "button";
    evaluate.disabled = !(card.photo || card.back_photo);
    evaluate.addEventListener("click", async () => {
      evaluate.disabled = true;
      error.textContent = "";
      status.textContent = "Évaluation des photos en cours…";
      try {
        const result = await api(`/copies/${card.id}/condition-assessments`, {
          method: "POST",
          body: JSON.stringify({ expected_version: card.version }),
        });
        card.condition_assessments = [
          result,
          ...(card.condition_assessments || []),
        ];
        if (panel.isConnected) renderConditionAssessment(parent, card, panel);
      } catch (e) {
        error.textContent = e.message;
        status.textContent = "L’état enregistré est conservé.";
      } finally {
        evaluate.disabled = false;
      }
    });
    panel.append(evaluate);
    if (!card.back_photo)
      panel.append(
        el(
          "p",
          "Ajoutez le verso pour examiner les deux faces. Avec une seule face, l’évaluation reste partielle.",
          "help",
        ),
      );
  }
  const assessment = card.condition_assessments?.[0];
  if (assessment) {
    const result = assessment.result;
    panel.append(
      el(
        "h4",
        `Proposition IA : ${result.suggested_condition || "indéterminable"}`,
      ),
    );
    panel.append(
      el(
        "p",
        `Photos ${result.front_usable && result.back_usable ? "recto et verso" : "partielles"} · qualité ${{ adequate: "exploitable", limited: "limitée", unusable: "inexploitable" }[result.quality]} · ${new Date(assessment.created_at).toLocaleString("fr-FR")}`,
        "help",
      ),
    );
    panel.append(el("p", result.explanation));
    for (const [label, flaws] of [
      ["Recto", result.flaws_front],
      ["Verso", result.flaws_back],
    ])
      if (flaws) panel.append(el("p", `${label} : ${flaws}`));
    const limits = el("ul", undefined, "assessment-limits");
    for (const limit of result.limits) limits.append(el("li", limit));
    panel.append(limits);
    if (assessment.stale)
      panel.append(
        el(
          "p",
          "Proposition obsolète : les photos ont changé. Demandez une nouvelle évaluation.",
          "error",
        ),
      );
    else if (editAllowed()) {
      const validation = el("form", undefined, "condition-validation");
      const label = el("label", "État retenu après examen");
      const grade = el("select");
      grade.required = true;
      grade.append(
        new Option("Choisir un état", ""),
        ...["NM", "EX", "GD", "LP", "PL", "PO", "NM/EX"].map(
          (value) => new Option(value, value),
        ),
      );
      grade.value = result.suggested_condition;
      label.append(grade);
      const checkLabel = el("label", undefined, "check-label");
      const check = el("input");
      check.type = "checkbox";
      check.required = true;
      checkLabel.append(
        check,
        document.createTextNode(
          "J’ai examiné la carte en main et je confirme l’état retenu.",
        ),
      );
      const reasonLabel = el("label", "Motif de validation de l’état");
      const reason = el("input");
      reason.required = true;
      reason.maxLength = 1000;
      reason.value = "Examen de la carte et comparaison aux observations IA";
      reasonLabel.append(reason);
      const save = el("button", "Enregistrer l’état vérifié", "primary");
      validation.append(label, checkLabel, reasonLabel, save);
      validation.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (save.disabled || !check.checked) return;
        save.disabled = true;
        error.textContent = "";
        try {
          const changed = await api(
            `/copies/${card.id}/condition-assessments/${assessment.id}/confirm`,
            {
              method: "POST",
              body: JSON.stringify({
                expected_version: card.version,
                condition: grade.value,
                human_confirmed: check.checked,
                reason: reason.value,
              }),
            },
          );
          Object.assign(card, changed);
          const fields = $("detail-body").querySelector(".detail-fields");
          fields.elements.condition.value = card.condition;
          fields.elements.condition_confirmed.checked = Boolean(
            card.condition_confirmed,
          );
          renderConditionAssessment(parent, card, panel);
          await loadCards();
          toast("État vérifié enregistré ; prix conservé.");
        } catch (e) {
          error.textContent = e.message;
        } finally {
          save.disabled = false;
        }
      });
      panel.append(validation);
    }
    if (card.condition_assessments.length > 1) {
      const history = el("details");
      history.append(
        el(
          "summary",
          `Évaluations précédentes (${card.condition_assessments.length - 1})`,
        ),
      );
      for (const past of card.condition_assessments.slice(1))
        history.append(
          el(
            "p",
            `${new Date(past.created_at).toLocaleString("fr-FR")} : ${past.result.suggested_condition || "indéterminable"}${past.stale ? " · photos remplacées" : ""} — ${past.result.explanation}`,
          ),
        );
      panel.append(history);
    }
  }
  panel.append(status, error);
  if (previous) previous.replaceWith(panel);
  else parent.append(panel);
}
function renderEditionCheck(parent, card, previous = null) {
  const panel = el("section", undefined, "condition-panel");
  panel.setAttribute("aria-label", "Contrôle de l’édition");
  panel.append(el("h3", "Contrôle de l’édition par l’image"));
  const status = el("p", "", "help");
  status.setAttribute("role", "status");
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  if (!card.edition_check_available)
    panel.append(
      el(
        "p",
        "Contrôle indisponible sur ce serveur (option vision non installée).",
        "help",
      ),
    );
  else if (editAllowed()) {
    panel.append(
      el(
        "p",
        "Compare la photo du recto, sur le serveur, aux images TCGdex des cartes de même nom. Ne modifie pas la fiche.",
        "help",
      ),
    );
    const run = el("button", "Comparer aux images TCGdex");
    run.type = "button";
    run.disabled =
      !card.photo || !card.catalog_id || card.identification_status !== "confirmed";
    run.addEventListener("click", async () => {
      run.disabled = true;
      error.textContent = "";
      status.textContent =
        "Comparaison en cours (la première fois, téléchargement des images)…";
      try {
        const result = await api(`/copies/${card.id}/edition-checks`, {
          method: "POST",
          body: JSON.stringify({ expected_version: card.version }),
        });
        card.edition_checks = [
          { ...result, current_proposal: result.proposal },
          ...(card.edition_checks || []),
        ];
        if (panel.isConnected) renderEditionCheck(parent, card, panel);
      } catch (e) {
        error.textContent = e.message;
        status.textContent = "La fiche est conservée.";
      } finally {
        run.disabled = false;
      }
    });
    panel.append(run);
  }
  const check = card.edition_checks?.[0];
  if (check) {
    const proposal = check.current_proposal || check.proposal;
    panel.append(
      el(
        "h4",
        {
          agree: "Édition confirmée par l’image",
          undecided: "Image indécise",
          disagree: "Désaccord avec l’édition de la fiche",
          unavailable: "Contrôle à relancer",
        }[proposal.status],
      ),
    );
    panel.append(el("p", proposal.reason));
    const scores = check.result.scores;
    const names = Object.fromEntries(
      check.result.gallery.map((g) => [g.id, g.set_name || g.id]),
    );
    const ranking = Object.keys(scores)
      .sort((a, b) => scores[b] - scores[a])
      .slice(0, 3);
    const list = el("ol", undefined, "help");
    for (const id of ranking)
      list.append(
        el(
          "li",
          `${names[id]} (${id}) · ${scores[id].toFixed(3)}${id === card.catalog_id ? " · édition de la fiche" : ""}`,
        ),
      );
    panel.append(
      list,
      el(
        "p",
        `${Object.keys(scores).length} impressions comparées · ${check.source} ${check.model} · ${new Date(check.created_at).toLocaleString("fr-FR")}`,
        "help",
      ),
    );
    if (check.stale)
      panel.append(
        el(
          "p",
          "Contrôle obsolète : la photo du recto a changé. Relancez la comparaison.",
          "error",
        ),
      );
    else if (check.kept)
      panel.append(
        el("p", "Édition de la fiche conservée après examen de la carte.", "help"),
      );
    else if (proposal.status === "disagree" && editAllowed() && !card.deleted_at) {
      const keep = el("form", undefined, "condition-validation");
      const reasonLabel = el("label", "Motif");
      const reason = el("input");
      reason.required = true;
      reason.maxLength = 1000;
      reason.value = "Édition vérifiée sur la carte malgré le contrôle par l’image";
      reasonLabel.append(reason);
      const save = el("button", "Garder l’édition de la fiche", "primary");
      keep.append(
        el(
          "p",
          "Pour corriger l’édition, utilisez l’identification de la fiche ; le contrôle sera recalculé.",
          "help",
        ),
        reasonLabel,
        save,
      );
      keep.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (save.disabled) return;
        save.disabled = true;
        error.textContent = "";
        try {
          await api(`/copies/${card.id}/edition-checks/${check.id}/keep`, {
            method: "POST",
            body: JSON.stringify({
              expected_version: card.version,
              reason: reason.value,
            }),
          });
          await loadCards();
          await openDetail(card.id);
          toast("Édition conservée ; la carte quitte « À examiner ».");
        } catch (e) {
          error.textContent = e.message;
        } finally {
          save.disabled = false;
        }
      });
      panel.append(keep);
    }
  }
  panel.append(status, error);
  if (previous) previous.replaceWith(panel);
  else parent.append(panel);
}
const languageNames = {
  fr: "français",
  en: "anglais",
  ja: "japonais",
  de: "allemand",
  es: "espagnol",
  it: "italien",
  pt: "portugais",
  ko: "coréen",
  zh: "chinois",
};
function renderLanguageCheck(panel, card, check, proposal, error) {
  // Readings made before card-finish-v2 do not report the text language.
  if (!check.result.text_language) return;
  panel.append(el("h4", "Langue du texte"));
  panel.append(
    el(
      "p",
      `Texte imprimé (hors nom) : ${languageNames[check.result.text_language] || "langue non lue"}`,
      "help",
    ),
  );
  const conflicts = proposal.language_conflicts || [];
  if (!conflicts.length || check.stale) return;
  if (check.language_kept) {
    panel.append(
      el("p", "Langue de la fiche conservée après examen de la carte.", "help"),
    );
    return;
  }
  const list = el("ul", undefined, "price-warnings");
  for (const conflict of conflicts) list.append(el("li", conflict));
  panel.append(list);
  if (!editAllowed() || card.deleted_at) return;
  const keep = el("form", undefined, "condition-validation");
  const reasonLabel = el("label", "Motif");
  const reason = el("input");
  reason.required = true;
  reason.maxLength = 1000;
  reason.value = "Langue vérifiée sur la carte malgré la lecture";
  reasonLabel.append(reason);
  const save = el("button", "Garder la langue de la fiche");
  keep.append(
    el(
      "p",
      "Pour corriger la langue, modifiez la fiche ; le contrôle sera recalculé.",
      "help",
    ),
    reasonLabel,
    save,
  );
  keep.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (save.disabled) return;
    save.disabled = true;
    error.textContent = "";
    try {
      await api(`/copies/${card.id}/variant-checks/${check.id}/keep-language`, {
        method: "POST",
        body: JSON.stringify({
          expected_version: card.version,
          reason: reason.value,
        }),
      });
      await loadCards();
      await openDetail(card.id);
      toast("Langue conservée ; la carte quitte « À examiner ».");
    } catch (e) {
      error.textContent = e.message;
    } finally {
      save.disabled = false;
    }
  });
  panel.append(keep);
}
const finishLabels = {
  non_holo: "Non holo (mate)",
  holo: "Holo dans l’illustration",
  holo_border: "Holo avec cadre brillant (Prime, LV.X…)",
  reverse: "Reverse (fond brillant)",
  special: "Autre finition / variante spéciale",
};
function renderVariantCheck(parent, card, previous = null) {
  const panel = el("section", undefined, "condition-panel");
  panel.setAttribute("aria-label", "Vérification de la finition et de la langue");
  panel.append(el("h3", "Vérification de la finition et de la langue"));
  panel.append(
    el(
      "p",
      `Fiche : ${finishLabels[card.finish] || "finition à déterminer"} · ${card.foil ? "Foil" : "Standard"} · ${card.variant_confirmed ? "vérifiée sur la carte" : "à confirmer"}`,
    ),
  );
  const status = el("p", "", "help");
  status.setAttribute("role", "status");
  const error = el("p", "", "error");
  error.setAttribute("role", "alert");
  if (editAllowed()) {
    panel.append(
      el(
        "p",
        "Cette action transmet la photo du recto à Gemini. La lecture propose une finition et contrôle la langue du texte ; elle ne modifie ni la fiche ni le prix.",
        "help",
      ),
    );
    const read = el("button", "Lire la finition", "primary");
    read.type = "button";
    read.disabled = !card.photo;
    read.addEventListener("click", async () => {
      read.disabled = true;
      error.textContent = "";
      status.textContent = "Lecture de la photo en cours…";
      try {
        const result = await api(
          `/copies/${card.id}/variant-checks?threshold=${reviewThreshold()}`,
          {
            method: "POST",
            body: JSON.stringify({ expected_version: card.version }),
          },
        );
        // The server recomputes the proposal against the current copy on reload.
        card.variant_checks = [
          { ...result, current_proposal: result.proposal },
          ...(card.variant_checks || []),
        ];
        if (panel.isConnected) renderVariantCheck(parent, card, panel);
      } catch (e) {
        error.textContent = e.message;
        status.textContent = "La fiche est conservée.";
      } finally {
        read.disabled = !card.photo;
      }
    });
    panel.append(read);
  }
  const check = card.variant_checks?.[0];
  if (check) {
    const reading = check.result;
    const proposal = check.current_proposal || check.proposal;
    const headline = {
      proposed: `Proposition : ${finishLabels[proposal.finish]} · ${proposal.foil ? "Foil" : "Standard"}`,
      examine: "Examen physique requis",
      unreadable: "Lecture impossible",
    }[proposal.status];
    panel.append(el("h4", headline));
    panel.append(
      el(
        "p",
        `Illustration ${{ holo: "holo", matte: "mate", unclear: "indéterminée" }[reading.artwork]} · fond ${{ visible: "brillant", not_visible: "mat", unclear: "indéterminé" }[reading.background_shine]} · tampon ${reading.stamp_text ? `« ${reading.stamp_text} »` : "non lu"} · ${check.source} ${check.model} · ${new Date(check.created_at).toLocaleString("fr-FR")}`,
        "help",
      ),
    );
    panel.append(el("p", proposal.reason));
    if (reading.notes) panel.append(el("p", reading.notes, "help"));
    if (proposal.conflicts.length) {
      const conflicts = el("ul", undefined, "price-warnings");
      for (const conflict of proposal.conflicts)
        conflicts.append(el("li", conflict));
      panel.append(conflicts);
    }
    if (check.stale)
      panel.append(
        el(
          "p",
          "Lecture obsolète : la photo du recto a changé. Demandez une nouvelle lecture.",
          "error",
        ),
      );
    else if (editAllowed() && !card.deleted_at) {
      const decision = el("form", undefined, "condition-validation");
      const finishLabel = el("label", "Finition retenue après examen");
      const finish = el("select");
      finish.required = true;
      finish.append(
        new Option("Choisir une finition", ""),
        ...Object.entries(finishLabels).map(
          ([value, label]) => new Option(label, value),
        ),
      );
      // Only a usable proposal pre-fills the choice; an examination starts blank.
      finish.value =
        proposal.status === "proposed" ? proposal.finish : card.finish || "";
      finishLabel.append(finish);
      const stampLabel = el("label", "Observation du tampon");
      const stampState = el("select");
      stampState.append(
        new Option("Non examiné", "unobserved"),
        new Option("Absence constatée", "absent"),
        new Option("Présent sur la carte", "present"),
      );
      stampState.value =
        card.stamp_state !== "unobserved"
          ? card.stamp_state
          : proposal.stamp
            ? "present"
            : "unobserved";
      stampLabel.append(stampState);
      const stampTextLabel = el("label", "Texte du tampon");
      const stamp = el("input");
      stamp.maxLength = 120;
      stamp.value = card.stamp_state !== "unobserved" ? card.stamp : proposal.stamp;
      stampTextLabel.append(stamp);
      const confirmLabel = el("label", undefined, "check-label");
      const confirmed = el("input");
      confirmed.type = "checkbox";
      confirmLabel.append(
        confirmed,
        document.createTextNode(
          "J’ai examiné la carte en main (variante et tampon vérifiés).",
        ),
      );
      const reasonLabel = el("label", "Motif");
      const reason = el("input");
      reason.required = true;
      reason.maxLength = 1000;
      reason.value = "Lecture de la finition comparée à la carte";
      reasonLabel.append(reason);
      const save = el("button", "Enregistrer la finition retenue", "primary");
      decision.append(
        finishLabel,
        stampLabel,
        stampTextLabel,
        confirmLabel,
        reasonLabel,
        save,
      );
      decision.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (save.disabled) return;
        save.disabled = true;
        error.textContent = "";
        try {
          await api(
            `/copies/${card.id}/variant-checks/${check.id}/confirm?threshold=${reviewThreshold()}`,
            {
              method: "POST",
              body: JSON.stringify({
                expected_version: card.version,
                finish: finish.value,
                stamp_state: stampState.value,
                stamp: stampState.value === "present" ? stamp.value : "",
                variant_confirmed: confirmed.checked,
                reason: reason.value,
              }),
            },
          );
          await loadCards();
          await openDetail(card.id);
          toast("Finition enregistrée ; catégorie de prix recalculée.");
        } catch (e) {
          error.textContent = e.message;
        } finally {
          save.disabled = false;
        }
      });
      panel.append(decision);
    }
    renderLanguageCheck(panel, card, check, proposal, error);
    if (card.variant_checks.length > 1) {
      const history = el("details");
      history.append(
        el("summary", `Lectures précédentes (${card.variant_checks.length - 1})`),
      );
      for (const past of card.variant_checks.slice(1))
        history.append(
          el(
            "p",
            `${new Date(past.created_at).toLocaleString("fr-FR")} : illustration ${past.result.artwork}${past.stale ? " · photo remplacée" : ""} — ${past.proposal.reason}`,
          ),
        );
      panel.append(history);
    }
  }
  panel.append(status, error);
  if (previous) previous.replaceWith(panel);
  else parent.append(panel);
}
// Beside the front photo: the edition as TCGdex shows it, to compare by eye.
async function renderCatalogueFigure(faces, c) {
  const figure = el("figure", undefined, "catalogue-figure");
  figure.append(el("figcaption", "Catalogue TCGdex"));
  faces.firstElementChild.after(figure);
  let info;
  try {
    info = await api(`/copies/${c.id}/catalogue`);
  } catch {
    figure.append(el("p", "Catalogue injoignable : rouvrez la fiche plus tard.", "help"));
    return;
  }
  if (info.image) {
    const image = el("img");
    image.src = info.image;
    image.alt = `Catalogue TCGdex de ${c.name} (${info.catalog_id})`;
    figure.append(image);
  } else figure.append(el("p", "TCGdex n’a pas d’image de cette édition.", "help"));
  figure.append(
    el(
      "p",
      "Impression standard de l’édition : TCGdex ne montre ni les reverses ni les tampons.",
      "help",
    ),
  );
  const links = el("div", undefined, "intake-actions");
  // The Cardmarket link lives in the price section, once.
  for (const [label, href] of [
    [`Données TCGdex (${info.served_language})`, info.tcgdex_url],
  ]) {
    if (!href) continue;
    const link = el("a", label);
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    links.append(link);
  }
  figure.append(links);
}
