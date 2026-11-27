"use strict";
// Storefront requests: nothing is reserved until a person accepts some cards.
async function loadRequests() {
  const box = $("requests-list");
  let requests;
  try {
    requests = await api("/requests");
  } catch (e) {
    box.replaceChildren(el("p", e.message, "error"));
    return;
  }
  box.replaceChildren();
  const open = requests.filter((r) => r.status === "sent");
  $("requests-count").textContent = open.length
    ? `${open.length} en attente`
    : "Aucune demande en attente";
  for (const request of requests) {
    const card = el("article", undefined, "sale-card");
    card.id = `demande-${request.id}`;
    if (request.id === focusedRequest()) card.classList.add("focused");
    const modeLabel = request.delivery === "hand" ? "Remise en main propre" : (request.registered ? "Recommandé R2" : "Envoi suivi");
    card.append(
      el("h3", `${request.display_name || request.email} · ${money(request.total_with_shipping_cents || request.total_cents)} · ${request.status_label}`),
      el(
        "p",
        `${request.email} · le ${new Date(request.created_at).toLocaleDateString("fr-FR")} · ${modeLabel}` +
          (request.shipping_cents ? ` (port ${money(request.shipping_cents)})` : "") +
          (request.reference ? ` · référence de paiement ${request.reference}` : ""),
        "sale-meta",
      ),
    );
    // Sent without an account: your first e-mail is what checks the address.
    if (!request.email_verified_at)
      card.append(el("p", "Adresse non prouvée : le lien transmis par le vendeur permet de rattacher les demandes invitées au compte.", "sale-meta"));
    if (!request.contact_known) {
      card.append(el("p", "Ancienne demande : l’adresse affichée est historique, sans preuve du destinataire d’origine. Vérifiez votre correspondance avant de la rattacher à un compte.", "notice"));
      if (state.user?.role === "admin") {
        const form = el("form", undefined, "stack");
        const email = el("input"), name = el("input"), evidence = el("input");
        email.type = "email";
        email.required = name.required = evidence.required = true;
        email.maxLength = 254;
        name.maxLength = 80;
        evidence.type = "checkbox";
        const emailLabel = el("label", "Adresse du destinataire retrouvée dans votre messagerie");
        const nameLabel = el("label", "Nom du destinataire");
        const evidenceLabel = el("label", "J’ai vérifié ces coordonnées dans ma correspondance.", "check-label");
        emailLabel.append(email);
        nameLabel.append(name);
        evidenceLabel.prepend(evidence);
        const confirm = el("button", "Confirmer les coordonnées de cette demande");
        confirm.type = "submit";
        form.append(emailLabel, nameLabel, evidenceLabel, confirm);
        form.onsubmit = async (event) => {
          event.preventDefault();
          if (confirm.disabled || !form.reportValidity()) return;
          confirm.disabled = true;
          try {
            await api(`/requests/${request.id}/contact`, { method: "PATCH", body: JSON.stringify({
              expected_version: request.version, email: email.value.trim(), display_name: name.value.trim(),
              correspondence_checked: evidence.checked,
            }) });
            toast("Coordonnées confirmées. Envoyez le lien de mot de passe depuis les comptes clients.");
            await loadRequests();
          } catch (error) { toast(error.message); }
          finally { confirm.disabled = false; }
        };
        card.append(form);
      }
    }
    if (request.message) card.append(el("p", `Message : ${request.message}`));
    if (request.decision) card.append(el("p", `Réponse : ${request.decision}`, "sale-meta"));
    const list = el("ul", undefined, "request-lines");
    const checks = [];
    const outcomes = { pending: "en attente", accepted: "acceptée", refused: "non retenue", unavailable: "plus disponible" };
    const stocks = { available: "", reserved: " (réservée)", sold: " (vendue)" };
    for (const item of request.items) {
      const line = el("li");
      const copies = item.copies
        .map((c) => `${c.name} ${c.number}${stocks[c.stock_state] ?? ""}`)
        .join(", ");
      if (request.status === "sent" && editAllowed()) {
        const label = el("label", undefined, "check-label"),
          check = el("input");
        check.type = "checkbox";
        check.checked = item.available;
        check.disabled = !item.available;
        check.value = item.listing_id;
        checks.push(check);
        label.append(check, document.createTextNode(`${item.label} · ${money(item.price_cents)}${item.available ? "" : " · plus disponible"}`));
        line.append(label, el("small", copies));
      } else {
        line.append(el("span", `${item.label} · ${money(item.price_cents)} · ${outcomes[item.outcome]}`), el("small", copies));
      }
      list.append(line);
    }
    card.append(list);
    if (request.status === "sent" && editAllowed()) {
      const accept = el("button", "Accepter les cartes cochées", "primary"),
        refuse = el("button", "Refuser la demande");
      accept.type = refuse.type = "button";
      accept.disabled = !request.contact_known;
      accept.addEventListener("click", async () => {
        const chosen = checks.filter((c) => c.checked).map((c) => c.value);
        if (!chosen.length) return toast("Cochez au moins une carte.");
        try {
          await api(`/requests/${request.id}/accept`, {
            method: "POST",
            body: JSON.stringify({ expected_version: request.version, listing_ids: chosen }),
          });
          toast(`Demande acceptée : lot réservé. Copiez la réponse pour ${request.email}.`);
          await loadSales();
        } catch (e) {
          toast(e.message);
          await loadRequests();
        }
      });
      refuse.addEventListener("click", async () => {
        const reason = prompt("Motif du refus, visible par le client :", "Désolée, ces cartes ne sont plus disponibles.");
        if (!reason) return;
        try {
          await api(`/requests/${request.id}/refuse`, {
            method: "POST",
            body: JSON.stringify({ expected_version: request.version, reason }),
          });
          await loadRequests();
        } catch (e) {
          toast(e.message);
        }
      });
      card.append(accept, refuse);
    }
    if (request.payment) {
      // A client without a password cannot open « Mes demandes »: the e-mail carries it.
      const copyReply = el("button", "Copier la réponse complète pour l’acheteur", "primary");
      copyReply.type = "button";
      copyReply.addEventListener("click", async () => {
        const text = request.reply_text || paymentText(request.payment);
        try {
          await navigator.clipboard.writeText(text);
          toast(`Réponse complète copiée : collez-la dans votre e-mail à ${request.email}.`);
        } catch {
          prompt(`Réponse à envoyer à ${request.email} :`, text);
        }
      });
      const copy = el("button", "Copier les instructions de paiement");
      copy.type = "button";
      copy.addEventListener("click", async () => {
        const text = paymentText(request.payment);
        try {
          await navigator.clipboard.writeText(text);
          toast(`Instructions copiées : collez-les dans votre e-mail à ${request.email}.`);
        } catch {
          prompt(`Instructions à envoyer à ${request.email} :`, text);
        }
      });
      card.append(copyReply, copy);
    }
    box.append(card);
  }
  const focusRequest = focusedRequest();
  const focused = focusRequest && document.getElementById(`demande-${focusRequest}`);
  if (focused) focused.scrollIntoView({ block: "start" });
  else if (focusRequest) toast("Cette demande n’est plus dans la liste : elle a peut-être déjà reçu une réponse.");
}
function paymentText(payment) {
  const lines = [
    `Montant à régler : ${money(payment.total_cents)}` +
      (payment.shipping_cents ? `, dont ${money(payment.shipping_cents)} de port.` : "."),
    `Référence à indiquer dans le libellé : ${payment.reference}.`,
  ];
  if (payment.wero) lines.push(`Wero : ${payment.wero}`);
  if (payment.iban)
    lines.push(`Virement : IBAN ${payment.iban.replace(/(.{4})/g, "$1 ").trim()}, titulaire ${payment.holder}`);
  if (payment.paypal) lines.push(`PayPal (biens et services) : ${payment.paypal}`);
  if (lines.length === 2) lines.push("Moyen de paiement : à convenir ensemble.");
  return lines.join("\n");
}
async function loadClients() {
  const box = $("clients-list");
  let clients;
  try {
    clients = await api("/clients");
  } catch (e) {
    box.replaceChildren(el("p", e.message, "error"));
    return;
  }
  box.replaceChildren();
  if (!clients.length) box.append(el("p", "Aucun client pour l’instant.", "help"));
  const labels = { pending: "en attente", active: "actif", refused: "refusé" };
  for (const client of clients) {
    const row = el("div", undefined, "user-access");
    row.append(
      el("strong", client.display_name || client.email),
      el("span", ` · ${client.email} · ${client.disabled ? "désactivé" : labels[client.status]} · depuis le ${new Date(client.created_at).toLocaleDateString("fr-FR")}`),
    );
    if (client.pending_email) row.append(el("p", `Adresse à confirmer : ${client.pending_email}. Envoyez le lien à cette adresse.`, "help"));
    const act = (text, status, disabled) => {
      const button = el("button", text);
      button.type = "button";
      button.addEventListener("click", async () => {
        try {
          await api("/clients/" + client.id, {
            method: "PATCH",
            body: JSON.stringify({ status, disabled }),
          });
          await loadClients();
        } catch (e) {
          toast(e.message);
        }
      });
      row.append(button);
    };
    if (client.status !== "active" || client.disabled) act("Valider", "active", false);
    if (client.status === "pending") act("Refuser", "refused", false);
    if (client.status === "active" && !client.disabled) act("Désactiver", "active", true);
    if (client.status !== "refused" && !client.disabled) {
      // No e-mail service: the seller pastes the link into their own reply.
      const link = el("button", "Lien de mot de passe");
      link.type = "button";
      link.addEventListener("click", async () => {
        try {
          const made = await api(`/clients/${client.id}/password-link`, { method: "POST" });
          const url = `${location.origin}/#mot-de-passe=${made.token}`;
          const until = new Date(made.expires_at).toLocaleDateString("fr-FR");
          try {
            await navigator.clipboard.writeText(url);
            toast(`Lien copié, valable une fois jusqu’au ${until} : collez-le dans votre e-mail à ${made.email}.`);
          } catch {
            prompt(`Lien valable une fois jusqu’au ${until}, à envoyer à ${made.email} :`, url);
          }
        } catch (e) {
          toast(e.message);
        }
      });
      row.append(link);
    }
    box.append(row);
  }
}
async function loadAudience() {
  const data = await api("/audience?days=" + $("audience-days").value);
  const number = (n) => n.toLocaleString("fr-FR");
  const date = (day, options) =>
    new Date(day + "T12:00:00").toLocaleDateString("fr-FR", options);
  $("audience-stats").replaceChildren(
    ...[
      [data.visitors, "visiteurs (cumul des jours)"],
      [data.page_views, "pages vues"],
      [data.listing_views, "ouvertures de fiche"],
      [data.requests, `demandes · ${data.signups} inscription(s)`],
    ].map(([value, label]) => {
      const tile = el("div", undefined, "stat");
      tile.append(el("strong", number(value)), el("span", label));
      return tile;
    }),
  );
  // A year of days would make hairline bars: weeks then, Monday first.
  let points = data.days.map((d) => ({ ...d, label: date(d.day, { weekday: "short", day: "numeric", month: "short" }) }));
  const weekly = points.length > 120;
  if (weekly) {
    const weeks = [];
    for (const d of data.days) {
      const monday = new Date(d.day + "T12:00:00");
      monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
      const key = monday.toISOString().slice(0, 10);
      if (weeks.at(-1)?.key !== key)
        weeks.push({ key, visitors: 0, pages: 0, label: "semaine du " + date(key, { day: "numeric", month: "short" }) });
      weeks.at(-1).visitors += d.visitors;
      weeks.at(-1).pages += d.pages;
    }
    points = weeks;
  }
  const top = Math.max(1, ...points.map((p) => p.visitors));
  $("audience-bars").replaceChildren(
    ...points.map((p) => {
      // A button: a tap or the keyboard shows the detail, not only a hover.
      const bar = el("button", undefined, "audience-bar");
      bar.type = "button";
      const fill = el("span");
      fill.style.height = `${(p.visitors / top) * 100}%`;
      const text = `${p.label} : ${number(p.visitors)} visiteur(s), ${number(p.pages)} page(s)`;
      bar.title = text;
      bar.setAttribute("aria-label", text);
      const show = () => { $("audience-detail").textContent = text; };
      for (const kind of ["click", "focus", "mouseenter"]) bar.addEventListener(kind, show);
      bar.append(fill);
      return bar;
    }),
  );
  $("audience-chart-title").textContent = weekly ? "Visiteurs par semaine" : "Visiteurs par jour";
  $("audience-range").textContent =
    `Du ${date(data.from, { day: "numeric", month: "long", year: "numeric" })} au ${date(data.to, { day: "numeric", month: "long", year: "numeric" })} · maximum ${number(top)} visiteur(s) ${weekly ? "par semaine" : "par jour"}. Touchez ou survolez une barre pour le détail.`;
  const list = (id, rows, empty) =>
    $(id).replaceChildren(
      ...(rows.length
        ? rows.map(([name, count]) => {
            const item = el("li");
            item.append(el("span", name), el("strong", number(count)));
            return item;
          })
        : [el("li", empty, "help")]),
    );
  list(
    "audience-listings",
    data.listings.map(({ title, status, count }) => {
      const label = title || "Annonce introuvable";
      const suffix = { withdrawn: " · retirée", unavailable: " · indisponible" };
      return [label + (suffix[status] || ""), count];
    }),
    "Aucune fiche ouverte sur la période.",
  );
  list(
    "audience-referrers",
    data.referrers.map((r) => [r.domain, r.count]),
    "Aucun site référent sur la période.",
  );
  list(
    "audience-devices",
    [
      ["Ordinateur", data.devices.desktop],
      ["Téléphone ou tablette", data.devices.mobile],
    ],
    "",
  );
}
$("audience-days").addEventListener("change", () =>
  loadAudience().catch((e) => toast(e.message)),
);
function matchesSalesFilter(sale, filter) {
  if (filter === "all") return true;
  if (filter === "draft" || filter === "reserved" || filter === "cancelled")
    return sale.status === filter;
  if (filter === "sold")
    return ["sold", "shipped", "completed", "returned"].includes(sale.status);
  return sale.status !== "cancelled";
}
async function loadSales() {
  if (typeof refreshTodo === "function") refreshTodo().catch(() => {});
  await loadRequests();
  const sales = await api("/sales");
  const filter = $("sales-filter")?.value || "active";
  const visible = sales.filter((sale) => matchesSalesFilter(sale, filter));
  const cancelled = sales.filter((sale) => sale.status === "cancelled").length;
  if ($("sales-count")) {
    const parts = [
      `${visible.length} lot${visible.length > 1 ? "s" : ""} affiché${visible.length > 1 ? "s" : ""}`,
    ];
    if (filter === "active" && cancelled)
      parts.push(
        `${cancelled} annulé${cancelled > 1 ? "s" : ""} masqué${cancelled > 1 ? "s" : ""}`,
      );
    $("sales-count").textContent = parts.join(" · ");
  }
  $("sales-list").replaceChildren();
  if (!visible.length) {
    const message = !sales.length
      ? editAllowed()
        ? "Aucun lot pour le moment. Cliquez sur « Créer un lot » pour choisir vos cartes."
        : "Aucun lot pour le moment."
      : filter === "active"
        ? editAllowed()
          ? "Aucun lot actif pour le moment. Cliquez sur « Créer un lot » pour choisir vos cartes."
          : "Aucun lot actif pour le moment."
        : "Aucun lot dans ce statut.";
    $("sales-list").append(el("p", message, "empty"));
    return;
  }
  const transitions = {
    draft: [
      ["reserved", "Réserver les cartes"],
      ["cancelled", "Annuler"],
    ],
    reserved: [
      ["sold", "Confirmer la vente"],
      ["cancelled", "Libérer la réservation"],
    ],
    sold: [
      ["shipped", "Marquer expédiée"],
      ["completed", "Clôturer"],
      ["returned", "Enregistrer un retour"],
    ],
    shipped: [
      ["completed", "Clôturer"],
      ["returned", "Enregistrer un retour"],
    ],
    completed: [["returned", "Enregistrer un retour"]],
    cancelled: [],
    returned: [],
  };
  for (const sale of visible) {
    const box = el("article", undefined, "sale");
    box.id = `vente-${sale.id}`;
    const heading = el("div", undefined, "sale-heading");
    heading.append(
      el("h2", sale.title),
      el(
        "span",
        saleLabels[sale.status],
        "badge " +
          (sale.status === "reserved"
            ? "reserved"
            : sale.status === "draft"
              ? "review"
              : "sold"),
      ),
    );
    box.append(
      heading,
      el(
        "p",
        `${sale.items.length} exemplaire${sale.items.length > 1 ? "s" : ""} · ${sale.channel || "Canal à préciser"} · ${sale.amount_cents == null ? "Prix convenu à préciser" : money(sale.amount_cents)}`,
        "sale-meta",
      ),
    );
    const items = el("div", undefined, "sale-items");
    for (const item of sale.items) {
      const button = el("button", `${item.name} · ${item.number}`);
      button.addEventListener("click", () =>
        openDetail(item.id).catch((e) => toast(e.message)),
      );
      items.append(button);
    }
    box.append(items);
    if (sale.agent_preparation) {
      const preparation = sale.agent_preparation;
      box.append(el("p", preparation.stale
        ? "Préparation par agent · des fiches ont changé : lot à revoir."
        : "Préparation par agent · à relire avant réservation ou publication.", "sale-meta"));
      const details = el("details"), summary = el("summary", "Lire le texte proposé");
      details.append(summary, el("pre", preparation.description, "agent-description"));
      box.append(details);
    }
    if (editAllowed()) {
      const draft = el("a", "Télécharger le brouillon d’annonce", "button");
      draft.href = `/api/sales/${sale.id}/listing-package`;
      box.append(draft);
    }
    box.append(
      el(
        "p",
        `${sale.paid ? "Paiement enregistré · net calculé" : "Net prévu"} : ${money(sale.net_cents)}`,
        "sale-total",
      ),
    );
    if (editAllowed()) {
      const form = el("form"),
        amounts = el("div", undefined, "sale-money");
      for (const [key, label] of [
        ["asking", "Prix affiché (€)"],
        ["target", "Prix cible (€)"],
        ["minimum", "Minimum (€)"],
        ["amount", "Prix (€)"],
        ["fees", "Frais (€)"],
        ["shipping_charged", "Port facturé (€)"],
        ["shipping_cost", "Coût du port (€)"],
        ["packing", "Emballage (€)"],
        ["refund", "Remboursé (€)"],
      ]) {
        const input = field(
          amounts,
          key + "_eur",
          label,
          sale[key + "_cents"] == null ? "" : sale[key + "_cents"] / 100,
          "number",
        );
        input.min = "0";
        input.step = ".01";
        input.required = !["asking", "target", "minimum"].includes(key);
      }
      form.append(amounts);
      field(form, "channel", "Canal", sale.channel);
      field(form, "listing_url", "Lien de l’annonce", sale.listing_url, "url");
      field(
        form,
        "notes",
        "Notes / expédition / retour",
        sale.notes,
        "textarea",
      );
      const paid = el("label", undefined, "check-label"),
        check = el("input");
      check.type = "checkbox";
      check.name = "paid";
      check.checked = Boolean(sale.paid);
      paid.append(check, document.createTextNode("Paiement reçu"));
      form.append(paid);
      const reason = field(form, "reason", "Motif de la mise à jour", "");
      reason.required = true;
      const actions = el("div", undefined, "sale-actions");
      const save = el("button", "Enregistrer");
      save.type = "submit";
      actions.append(save);
      for (const [target, label] of transitions[sale.status]) {
        const button = el(
          "button",
          label,
          target === "reserved" || target === "sold" ? "primary" : "",
        );
        button.type = "submit";
        button.dataset.target = target;
        actions.append(button);
      }
      form.append(actions);
      const error = el("p", "", "error");
      error.setAttribute("role", "alert");
      form.append(error);
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = new FormData(form),
          changes = {
            expected_version: sale.version,
            reason: data.get("reason"),
            paid: data.has("paid"),
            channel: data.get("channel"),
            listing_url: data.get("listing_url"),
            notes: data.get("notes"),
          };
        for (const key of [
          "amount",
          "fees",
          "shipping_charged",
          "shipping_cost",
          "packing",
          "refund",
          "asking",
          "target",
          "minimum",
        ])
          changes[key + "_eur"] =
            data.get(key + "_eur") === ""
              ? null
              : Number(data.get(key + "_eur"));
        if (e.submitter.dataset.target)
          changes.status = e.submitter.dataset.target;
        if (sale.agent_preparation && changes.amount_eur == null)
          delete changes.amount_eur;
        try {
          await api("/sales/" + sale.id, {
            method: "PATCH",
            body: JSON.stringify(changes),
          });
          state.selected.clear();
          state.lotMode = false;
          selectionBar();
          await refreshSummary();
          await loadCards();
          await loadSales();
          toast("Vente et stock mis à jour.");
        } catch (err) {
          error.textContent = err.message;
        }
      });
      if (sale.status === "cancelled") {
        const details = el("details"),
          summary = el("summary", "Détails et notes du lot annulé");
        details.append(summary, form);
        box.append(details);
      } else {
        box.append(form);
      }
    } else if (sale.notes) box.append(el("p", sale.notes, "sale-meta"));
    $("sales-list").append(box);
  }
}
async function loadPayment() {
  const payment = await api("/settings/payment");
  const form = $("payment-form");
  for (const [name, value] of Object.entries(payment)) form.elements[name].value = value;
}
async function loadFloorMargin() {
  const data = await api("/settings/floor-margin");
  $("floor-margin-form").elements.margin.value = data.margin;
  $("floor-margin-history").replaceChildren(
    ...data.history.map((h) =>
      el(
        "li",
        `${new Date(h.at).toLocaleString("fr-FR")} · ${h.actor} : ${
          h.previous === null ? "" : `${h.previous} % → `
        }${h.margin} % — ${h.reason}`,
      ),
    ),
  );
}
async function loadLotRotation() {
  const data = await api("/settings/lot-rotation");
  $("lot-rotation-form").elements.days.value = data.days;
  $("lot-rotation-history").replaceChildren(
    ...data.history.map((h) =>
      el(
        "li",
        t("lot_rotation.history", {
          at: new Date(h.at).toLocaleString(),
          actor: h.actor,
          previous: h.previous,
          days: h.days,
        }),
      ),
    ),
  );
}
async function loadUsers() {
  window.lilydexPush?.refresh();
  if (typeof Workflows !== "undefined") await Workflows.backupStatus();
  const users = await api("/users");
  await loadClients();
  await loadPayment();
  await loadFloorMargin();
  await loadLotRotation();
  $("users-list").replaceChildren();
  for (const u of users) {
    const row = el("form", undefined, "user-access");
    row.append(el("strong", u.username));
    field(row, "role", "Accès", u.role, "text", [
      ["reader", "Consultation"],
      ["editor", "Gestion"],
      ["admin", "Administration"],
    ]);
    const active = el("label", undefined, "check-label"),
      check = el("input");
    check.type = "checkbox";
    check.name = "active";
    check.checked = !u.disabled;
    active.append(check, document.createTextNode("Compte actif"));
    row.append(active);
    const button = el("button", "Modifier l’accès");
    button.type = "submit";
    row.append(button);
    row.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = new FormData(row);
      try {
        await api("/users/" + u.id, {
          method: "PATCH",
          body: JSON.stringify({
            role: data.get("role"),
            disabled: !data.has("active"),
          }),
        });
        if (u.id === state.user.id) {
          showAccess();
          toast("Accès modifié. Reconnectez-vous.");
        } else {
          await loadUsers();
          toast("Accès mis à jour ; sessions précédentes fermées.");
        }
      } catch (err) {
        toast(err.message);
      }
    });
    $("users-list").append(row);
  }
}
