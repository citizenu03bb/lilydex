"use strict";
// Binder import (decision 0047): photos go up by chunks from a queue kept in the
// browser until the server acknowledges them; the server does the reading.
const BinderImport = (() => {
  const CHUNK = 512 * 1024;
  let current = null,
    sending = false,
    poll = null,
    reported = null;
  const post = (path, data) =>
    api(path, { method: "POST", ...(data ? { body: JSON.stringify(data) } : {}) });
  const euros = (value) =>
    new Intl.NumberFormat(t.locale || "fr", { style: "currency", currency: "EUR" }).format(value);

  // -- The queue: IndexedDB when available, memory otherwise. ---------------
  const memory = new Map();
  let database = null;
  function open() {
    if (database !== null) return database;
    database = new Promise((resolve) => {
      if (typeof indexedDB === "undefined") return resolve(undefined);
      const request = indexedDB.open("lilydex-binder", 1);
      request.onupgradeneeded = () => request.result.createObjectStore("queue", { keyPath: "key" });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(undefined);
    });
    return database;
  }
  async function store(mode, action) {
    const db = await open();
    if (!db) return action(null);
    return new Promise((resolve, reject) => {
      const tx = db.transaction("queue", mode);
      const request = action(tx.objectStore("queue"));
      tx.oncomplete = () => resolve(request?.result);
      tx.onerror = () => reject(tx.error);
    });
  }
  const queued = async () =>
    (await store("readonly", (s) => (s ? s.getAll() : null))) || [...memory.values()];
  async function enqueue(item) {
    memory.set(item.key, item);
    await store("readwrite", (s) => s?.put(item));
  }
  async function dequeue(key) {
    memory.delete(key);
    await store("readwrite", (s) => s?.delete(key));
  }

  async function sha256(blob) {
    const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function add(file, page, position = 0) {
    if (!current || !file) return;
    const sha = await sha256(file);
    await enqueue({
      key: `${current.id}:${page}:${position}:${sha}`,
      importId: current.id,
      page,
      position,
      sha,
      blob: file,
    });
    send();
  }

  // One photo at a time, resumed where the server says it stopped.
  async function send() {
    if (sending) return;
    sending = true;
    try {
      for (const item of (await queued()).sort((a, b) => a.page - b.page || a.position - b.position)) {
        status(t("binder.sending", { page: item.page, percent: 0 }));
        let upload = await post(`/binder-imports/${item.importId}/uploads`, {
          page: item.page,
          position: item.position,
          size: item.blob.size,
          sha256: item.sha,
        });
        while (!upload.done) {
          const chunk = item.blob.slice(upload.received, upload.received + CHUNK);
          upload = await api(`/binder-uploads/${upload.id}?offset=${upload.received}`, {
            method: "PUT",
            body: chunk,
            headers: { "Content-Type": "application/octet-stream" },
          });
          status(
            t("binder.sending", {
              page: item.page,
              percent: Math.round((100 * upload.received) / upload.size),
            }),
          );
        }
        await dequeue(item.key);
      }
      status("");
    } catch (error) {
      // Offline or refused: the queue stays, and the next try resumes it.
      status(t("binder.send_paused", { reason: error.message }));
      setTimeout(send, 15000);
    } finally {
      sending = false;
      if (current) refresh();
    }
  }
  if (typeof window !== "undefined") window.addEventListener("online", () => send());

  // -- The dialog -------------------------------------------------------------
  function status(text) {
    $("binder-status").textContent = text;
  }
  function nextPage() {
    return Math.max(0, ...(current?.pages || []).map((p) => p.page)) + 1;
  }
  const pocketPhoto = (importId, page, position) =>
    `/api/binder-imports/${importId}/pages/${page}/pockets/${position}/photo`;

  function pocketActions(item, page, pocket) {
    const box = el("div", null);
    box.className = "binder-pocket";
    const img = el("img");
    img.src = pocketPhoto(item.id, page.page, pocket.position);
    img.alt = t("binder.pocket", { page: page.page, position: pocket.position });
    img.loading = "lazy";
    const retake = el("button", t("binder.retake_card"));
    retake.type = "button";
    retake.onclick = () => CardMedia.capture((file) => add(file, page.page, pocket.position));
    const empty = el("button", t("binder.mark_empty"));
    empty.type = "button";
    empty.onclick = async () => render(await post(`/binder-imports/${item.id}/pages/${page.page}/pockets/${pocket.position}/empty`));
    box.append(img, el("p", t("binder.pocket", { page: page.page, position: pocket.position }) + " · " + pocket.error), retake, empty);
    return box;
  }

  function render(item) {
    if (item?.id !== current?.id) reported = null;
    current = item;
    const panel = $("binder-current");
    panel.hidden = !item;
    if (!item) return;
    $("binder-title").textContent = t("binder.current", { album: item.album });
    $("binder-cost").textContent = t("binder.cost", {
      cost: euros(item.cost.eur),
      budget: euros(item.budget_eur),
    });
    $("binder-progress").textContent = t("binder.progress", {
      settled: item.progress.settled,
      pockets: item.progress.pockets,
      done: item.progress.pages_done,
      count: item.pages.length,
    });
    $("binder-note").textContent = item.note || "";
    $("binder-continue").hidden = item.status !== "paused_budget";
    $("binder-next-page").textContent = t("binder.shoot_page", { page: nextPage() });
    const list = $("binder-pages");
    list.replaceChildren();
    for (const page of item.pages) {
      const row = el("li");
      const review = page.review || {};
      let text = t(`binder.page_status.${page.status}`, { page: page.page });
      text += " · " + euros(page.cost_eur);
      if (page.status === "done" && review.confirmed !== undefined)
        text +=
          " · " +
          (review.applied
            ? t("binder.review_applied", { count: review.confirmed })
            : t("binder.review_simulated", { count: review.confirmed }));
      row.append(el("span", text));
      if (page.status === "error") {
        row.append(el("p", page.error));
        const again = el("button", t("binder.retake_page"));
        again.type = "button";
        again.onclick = () => CardMedia.capture((file) => add(file, page.page));
        row.append(again);
      }
      for (const pocket of page.pockets.filter((p) => ["retake", "failed"].includes(p.status)))
        row.append(pocketActions(item, page, pocket));
      list.append(row);
    }
    if (item.progress.pages_done !== reported) {
      reported = item.progress.pages_done;
      api(`/binder-imports/${item.id}/report`)
        .then((report) => {
          $("binder-reference").textContent = t("binder.reference", {
            queued: report.queued.length,
            tally: report.tally.editions,
            copies: report.tally.copies,
          });
        })
        .catch(() => {});
    }
    clearTimeout(poll);
    if ($("binder-dialog").open && item.status === "active" && item.progress.pages_done < item.pages.length)
      poll = setTimeout(refresh, 5000);
  }

  async function refresh() {
    if (!current) return;
    try {
      render(await api(`/binder-imports/${current.id}`));
    } catch (error) {
      status(error.message);
    }
  }

  async function openDialog() {
    $("binder-error").textContent = "";
    const imports = await api("/binder-imports");
    const select = $("binder-form").elements.import_id;
    select.replaceChildren(el("option", t("binder.new")));
    select.firstChild.value = "";
    for (const item of imports.filter((i) => i.status !== "closed")) {
      const option = el("option", `${item.album} · ${item.created_at.slice(0, 10)}`);
      option.value = item.id;
      select.append(option);
    }
    render(imports.find((i) => i.status !== "closed") || null);
    if (current) select.value = current.id;
    $("binder-new").hidden = Boolean(current);
    $("binder-dialog").showModal();
    send();
  }

  function attach() {
    const button = $("capture-binder");
    if (!button) return;
    button.hidden = state.user?.role !== "admin";
    button.onclick = () => openDialog().catch((e) => toast(e.message));
    $("binder-form").elements.import_id.onchange = async (event) => {
      const id = event.target.value;
      $("binder-new").hidden = Boolean(id);
      render(id ? await api(`/binder-imports/${id}`) : null);
    };
    $("binder-form").onsubmit = async (event) => {
      event.preventDefault();
      const values = event.target.elements;
      try {
        const item = await post("/binder-imports", {
          album_name: values.album_name.value,
          grid: values.grid.value,
        });
        await openDialog();
        render(item);
        values.import_id.value = item.id;
        $("binder-new").hidden = true;
      } catch (error) {
        $("binder-error").textContent = error.message;
      }
    };
    $("binder-next-page").onclick = () => CardMedia.capture((file) => add(file, nextPage()));
    $("binder-files").onchange = async (event) => {
      const files = [...event.target.files];
      event.target.value = "";
      let page = nextPage();
      for (const file of files) await add(file, page++);
    };
    $("binder-continue").onclick = async () => render(await post(`/binder-imports/${current.id}/continue`));
    $("binder-close").onclick = async () => {
      if (!confirm(t("binder.close_confirm"))) return;
      render(null);
      await post(`/binder-imports/${$("binder-form").elements.import_id.value}/close`);
      $("binder-dialog").close();
    };
  }

  return Object.freeze({ attach, add, send, render });
})();
