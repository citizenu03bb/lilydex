"use strict";

// Photos the review agent asks for, in binder order (agent_review.py). A new
// photo closes the request; the server then reads the card again on its own.
const photoRequestViews = ["front", "back", "holo", "corner"];
async function refreshPhotoRequests() {
  const panel = $("photo-requests");
  if (!editAllowed()) {
    panel.hidden = true;
    return;
  }
  const requests = await api("/photo-requests");
  panel.replaceChildren();
  panel.hidden = !requests.length;
  if (!requests.length) return;
  const title = el("h2", t("photo_requests.title"));
  title.id = "photo-requests-title";
  panel.append(
    title,
    el(
      "p",
      t("photo_requests.help", {
        count: new Set(requests.map((r) => r.copy_id)).size,
      }),
      "help",
    ),
  );
  const list = el("ol", undefined, "photo-requests");
  for (const request of requests) {
    const item = el("li", undefined, "workflow-actions");
    item.id = `photo-request-${request.copy_id}-${request.side}`;
    const view = photoRequestViews.includes(request.view) ? request.view : "front";
    const place = t("photo_requests.place", {
      album: request.album,
      page: request.page,
      position: request.position,
    });
    const text = el("span");
    text.append(
      el("strong", `${request.name} ${request.number}`),
      document.createTextNode(` · ${place} · `),
      el("em", t(`photo_requests.view.${view}`)),
      el("br"),
      document.createTextNode(request.reason),
    );
    const input = el("input");
    input.type = "file";
    input.accept = "image/*";
    input.setAttribute("capture", "environment");
    input.hidden = true;
    const take = el("button", t("photo_requests.take"), "primary");
    take.type = "button";
    take.onclick = () => input.click();
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      take.disabled = true;
      take.textContent = t("photo_requests.sending");
      try {
        const card = await api(`/copies/${request.copy_id}`);
        await api(
          `/copies/${request.copy_id}/photo?version=${card.version}&side=${request.side}` +
            (view === "holo" ? "&view=glint" : ""),
          {
            method: "PUT",
            body: file,
            headers: { "Content-Type": file.type || "image/jpeg" },
          },
        );
        toast(t("photo_requests.sent"));
        await refreshPhotoRequests();
        refreshTodo().catch(() => {});
      } catch (error) {
        toast(error.message);
        take.disabled = false;
        take.textContent = t("photo_requests.take");
      }
    };
    const open = el("button", t("photo_requests.open"));
    open.type = "button";
    open.onclick = () => openDetail(request.copy_id).catch((e) => toast(e.message));
    item.append(text, take, open, input);
    list.append(item);
  }
  panel.append(list);
}

// Prices under the anti-undercut floor that an agent may not apply: a person
// keeps the asked price, raises it to the floor, or refuses (floor_requests.py).
async function refreshFloorRequests() {
  const panel = $("floor-requests");
  if (!editAllowed()) {
    panel.hidden = true;
    return;
  }
  const requests = await api("/floor-requests");
  panel.replaceChildren();
  panel.hidden = !requests.length;
  if (!requests.length) return;
  const title = el("h2", t("floor_requests.title"));
  title.id = "floor-requests-title";
  panel.append(
    title,
    el("p", t("floor_requests.help", { count: requests.length }), "help"),
  );
  const list = el("ol", undefined, "floor-requests");
  for (const request of requests) {
    const item = el("li", undefined, "workflow-actions");
    item.id = `floor-request-${request.id}`;
    const names = request.items.map((i) => `${i.name} ${i.number}`).join(", ");
    const text = el("span");
    text.append(
      el("strong", request.lot ? request.title || names : names),
      document.createTextNode(
        " · " +
          t("floor_requests.prices", {
            price: formatEuros(request.price_cents),
            floor: formatEuros(request.current_floor_cents),
            reference: formatEuros(request.total_reference_cents),
          }),
      ),
      el("br"),
      document.createTextNode(request.reason),
    );
    if (request.lot) text.append(el("br"), document.createTextNode(names));
    const decide = (action, done) => async () => {
      for (const button of item.querySelectorAll("button")) button.disabled = true;
      try {
        await api(`/floor-requests/${request.id}/${action}`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        toast(done());
        await refreshFloorRequests();
        refreshTodo().catch(() => {});
      } catch (error) {
        toast(error.message);
        for (const button of item.querySelectorAll("button")) button.disabled = false;
      }
    };
    const accept = el("button", t("floor_requests.accept"), "primary");
    accept.type = "button";
    accept.onclick = decide("accept", () => t("floor_requests.accepted"));
    const raise = el(
      "button",
      t("floor_requests.raise", { floor: formatEuros(request.current_floor_cents) }),
    );
    raise.type = "button";
    raise.onclick = decide("raise", () => t("floor_requests.raised"));
    const refuse = el("button", t("floor_requests.refuse"));
    refuse.type = "button";
    refuse.onclick = decide("refuse", () => t("floor_requests.refused"));
    item.append(text, accept, raise, refuse);
    list.append(item);
  }
  panel.append(list);
}
