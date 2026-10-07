/* Shared private-image viewer and camera capture; no external photo service. */

"use strict";
const CardMedia = (() => {
  const node = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  let viewer,
    origin,
    camera,
    stream,
    request = 0;
  let resizeObservers = [];
  let guideObserver;
  // Framing guide of captured files, sent so the server can crop on it.
  const guides = new WeakMap();
  // Card outline (63 × 88 mm, portrait) centred in the frame, as fractions.
  function guideRect(width, height) {
    let h = 0.8,
      w = (h * height * 63) / 88 / width;
    if (w > 0.8) {
      h = (h * 0.8) / w;
      w = 0.8;
    }
    return { x: (1 - w) / 2, y: (1 - h) / 2, w, h };
  }
  function photoHeaders(file) {
    const g = guides.get(file);
    return {
      "Content-Type": file.type,
      ...(g
        ? {
            "X-Card-Guide": [g.x, g.y, g.w, g.h]
              .map((v) => v.toFixed(4))
              .join(","),
          }
        : {}),
    };
  }
  function zoomButton(image) {
    const button = node("button", null, "media-zoom");
    button.type = "button";
    button.setAttribute("aria-label", "Agrandir " + (image.alt || "la photo"));
    button.append(image, node("span", "⤢", "media-zoom-mark"));
    button.addEventListener("click", () => show(image, button));
    return button;
  }
  function enhance() {
    for (const image of document.querySelectorAll(
      "#workspace img, #detail-dialog img, #add-dialog img, #photo-dialog img",
    )) {
      if (image.closest("button")) continue;
      const parent = image.parentNode,
        next = image.nextSibling;
      parent.insertBefore(zoomButton(image), next);
    }
  }
  function show(image, trigger) {
    if (!image.src || image.hidden) return;
    if (!viewer) {
      viewer = node("dialog", null, "media-lightbox");
      viewer.setAttribute("aria-label", "Photos agrandies");
      viewer.addEventListener("close", () => {
        resizeObservers.forEach((observer) => observer.disconnect());
        resizeObservers = [];
        viewer.replaceChildren();
        if (origin?.isConnected) origin.focus({ preventScroll: true });
      });
      viewer.addEventListener("click", (e) => {
        if (e.target === viewer) {
          const r = viewer.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            viewer.close();
        }
      });
      document.body.append(viewer);
    }
    origin = trigger;
    const header = node("div", null, "dialog-header");
    header.append(node("h2", "Photos agrandies"));
    const close = node("button", "×", "close");
    close.setAttribute("aria-label", "Fermer les photos agrandies");
    close.addEventListener("click", () => viewer.close());
    header.append(close);
    const gallery = node("div", null, "media-gallery");
    const comparison = image.closest("#intake-comparison, [data-media-group]");
    const images = comparison
      ? Array.from(comparison.querySelectorAll("img"))
      : [image];
    for (const source of images) {
      const figure = node("figure");
      figure.append(node("figcaption", source.alt || "Photo de carte"));
      const controls = node("div", null, "media-controls");
      const label = node("label", "Zoom");
      const range = node("input");
      range.type = "range";
      range.min = "1";
      range.max = "4";
      range.step = "0.25";
      range.value = "1";
      range.setAttribute("aria-label", "Zoom « " + source.alt + " »");
      label.append(range);
      const reset = node("button", "Ajuster");
      const output = node("output", "100 %");
      controls.append(label, output, reset);
      const frame = node("div", null, "media-frame");
      frame.tabIndex = 0;
      frame.setAttribute(
        "aria-label",
        "Déplacer la photo agrandie « " + source.alt + " »",
      );
      const large = node("img");
      large.alt = source.alt;
      large.draggable = false;
      const original = source.currentSrc || source.src;
      large.src = original.startsWith("https://assets.tcgdex.net/")
        ? original.replace(/\/low\.webp$/, "/high.webp")
        : original;
      const error = node("p", "", "error");
      large.addEventListener("error", () => {
        if (large.src !== original) large.src = original;
        else
          error.textContent =
            "Photo indisponible. Fermez cet aperçu et actualisez la fiche.";
      });
      const update = () => {
        const fitted =
          large.naturalWidth && large.naturalHeight
            ? Math.min(
                frame.clientWidth,
                (parseFloat(getComputedStyle(frame).maxHeight) *
                  large.naturalWidth) /
                  large.naturalHeight,
              )
            : frame.clientWidth;
        large.style.width = `${fitted * Number(range.value)}px`;
        output.textContent = `${100 * Number(range.value)} %`;
        frame.classList.toggle("is-zoomed", Number(range.value) > 1);
      };
      let pan;
      frame.addEventListener("pointerdown", (event) => {
        // Touch scrolling remains native, including inertia and page gestures.
        if (
          event.pointerType === "touch" ||
          event.button !== 0 ||
          Number(range.value) === 1
        )
          return;
        event.preventDefault();
        frame.focus({ preventScroll: true });
        pan = {
          id: event.pointerId,
          x: event.clientX,
          y: event.clientY,
          left: frame.scrollLeft,
          top: frame.scrollTop,
        };
        frame.setPointerCapture(event.pointerId);
        frame.classList.add("is-panning");
      });
      frame.addEventListener("pointermove", (event) => {
        if (!pan || event.pointerId !== pan.id) return;
        frame.scrollLeft = pan.left + pan.x - event.clientX;
        frame.scrollTop = pan.top + pan.y - event.clientY;
      });
      const endPan = () => {
        pan = null;
        frame.classList.remove("is-panning");
      };
      for (const event of ["pointerup", "pointercancel", "lostpointercapture"])
        frame.addEventListener(event, endPan);
      range.addEventListener("input", update);
      large.addEventListener("load", update);
      const observer = new ResizeObserver(update);
      observer.observe(frame);
      resizeObservers.push(observer);
      reset.addEventListener("click", () => {
        range.value = "1";
        update();
        frame.scrollTo(0, 0);
      });
      frame.append(large);
      figure.append(
        controls,
        node("p", "Glissez l’image zoomée pour la déplacer.", "media-hint"),
        frame,
        error,
      );
      gallery.append(figure);
    }
    viewer.replaceChildren(header, gallery);
    viewer.showModal();
  }
  function stopCamera() {
    ++request;
    guideObserver?.disconnect();
    guideObserver = null;
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    const video = camera?.querySelector("video");
    if (video) video.srcObject = null;
  }
  const nativeCamera =
    /Android|iPhone|iPad/.test(navigator.userAgent) &&
    navigator.maxTouchPoints > 0;
  function chooseFile(callback, native = false) {
    const input = node("input");
    input.type = "file";
    input.accept = "image/jpeg,image/png,image/webp";
    if (native) input.setAttribute("capture", "environment");
    input.hidden = true;
    // Keep the picker in the active modal's top layer.
    (camera?.open
      ? camera
      : document.querySelector("dialog[open]") || document.body
    ).append(input);
    input.addEventListener(
      "change",
      () => {
        const file = input.files[0];
        input.remove();
        if (file) callback(file);
      },
      { once: true },
    );
    input.addEventListener("cancel", () => input.remove(), { once: true });
    input.click();
  }
  async function capture(callback) {
    if (nativeCamera) {
      chooseFile(callback, true);
      return;
    }
    if (camera?.open) return;
    if (!camera) {
      camera = node("dialog", null, "media-camera");
      camera.setAttribute("aria-label", "Prendre une photo avec la caméra");
      camera.addEventListener("close", stopCamera);
      document.body.append(camera);
    }
    const header = node("div", null, "dialog-header");
    header.append(node("h2", "Prendre une photo"));
    const close = node("button", "×", "close");
    close.setAttribute("aria-label", "Fermer la caméra");
    close.addEventListener("click", () => camera.close());
    header.append(close);
    const content = node("div", null, "dialog-form");
    const video = node("video");
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    const stage = node("div", null, "media-camera-stage");
    const guide = node("div", null, "media-camera-guide");
    guide.setAttribute("aria-hidden", "true");
    guide.hidden = true;
    stage.append(video, guide);
    // Place the guide on the displayed picture, inside object-fit letterboxing.
    const placeGuide = () => {
      if (!video.videoWidth || !video.clientWidth) return;
      const scale = Math.min(
        video.clientWidth / video.videoWidth,
        video.clientHeight / video.videoHeight,
      );
      const shownWidth = video.videoWidth * scale,
        shownHeight = video.videoHeight * scale;
      const g = guideRect(video.videoWidth, video.videoHeight);
      Object.assign(guide.style, {
        left: `${(video.clientWidth - shownWidth) / 2 + g.x * shownWidth}px`,
        top: `${(video.clientHeight - shownHeight) / 2 + g.y * shownHeight}px`,
        width: `${g.w * shownWidth}px`,
        height: `${g.h * shownHeight}px`,
      });
      guide.hidden = false;
    };
    video.addEventListener("loadedmetadata", placeGuide);
    video.addEventListener("resize", placeGuide);
    const label = node("label", "Caméra");
    label.hidden = true;
    const devices = node("select");
    label.append(devices);
    const status = node("p", "Autorisez la caméra pour afficher l’aperçu.");
    status.setAttribute("role", "status");
    const take = node("button", "Capturer la photo", "primary");
    take.disabled = true;
    const upload = node("button", "Téléverser une image à la place");
    upload.addEventListener("click", () =>
      chooseFile((file) => {
        camera.close();
        callback(file);
      }),
    );
    content.append(stage, label, status, take, upload);
    camera.replaceChildren(header, content);
    camera.showModal();
    async function start(deviceId) {
      stopCamera();
      const generation = request;
      take.disabled = true;
      guide.hidden = true;
      guideObserver = new ResizeObserver(placeGuide);
      guideObserver.observe(video);
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        status.textContent =
          "La caméra nécessite HTTPS ou localhost. Utilisez le lien HTTPS, ou téléversez une image.";
        label.hidden = true;
        return;
      }
      try {
        const obtained = await navigator.mediaDevices.getUserMedia({
          audio: false,
          // A landscape ideal makes Chrome crop portrait cameras (1280×2560 →
          // 1280×1080); a square ideal keeps the native frame in either way.
          video: {
            width: { ideal: 4096 },
            height: { ideal: 4096 },
            resizeMode: { ideal: "none" },
            ...(deviceId
              ? { deviceId: { exact: deviceId } }
              : { facingMode: { ideal: "environment" } }),
          },
        });
        if (generation !== request || !camera.open) {
          obtained.getTracks().forEach((track) => track.stop());
          return;
        }
        stream = obtained;
        video.srcObject = stream;
        await video.play();
        if (generation !== request || !camera.open) return;
        take.disabled = false;
        status.textContent =
          "Placez une seule carte dans le cadre, puis capturez la photo. Aucun enregistrement automatique.";
        const cameras = (
          await navigator.mediaDevices.enumerateDevices()
        ).filter((d) => d.kind === "videoinput");
        if (generation !== request || !camera.open) return;
        devices.replaceChildren(
          ...cameras.map(
            (d, i) => new Option(d.label || `Caméra ${i + 1}`, d.deviceId),
          ),
        );
        devices.value = stream.getVideoTracks()[0].getSettings().deviceId || "";
        label.hidden = cameras.length < 2;
      } catch (error) {
        if (generation !== request || !camera.open) return;
        stopCamera();
        label.hidden = true;
        status.textContent =
          error.name === "NotAllowedError"
            ? "Accès à la caméra refusé. Autorisez-le dans le navigateur ou téléversez une image."
            : error.name === "NotFoundError"
              ? "Aucune caméra disponible. Vous pouvez téléverser une image."
              : "La caméra n’a pas pu démarrer. Fermez les autres applications qui l’utilisent, ou téléversez une image.";
      }
    }
    devices.addEventListener("change", () => start(devices.value));
    take.addEventListener("click", async () => {
      if (!video.videoWidth || !stream || take.disabled) return;
      take.disabled = true;
      const canvas = node("canvas");
      const ratio = Math.min(
        1,
        1600 / Math.max(video.videoWidth, video.videoHeight),
      );
      canvas.width = Math.round(video.videoWidth * ratio);
      canvas.height = Math.round(video.videoHeight * ratio);
      canvas
        .getContext("2d")
        .drawImage(video, 0, 0, canvas.width, canvas.height);
      const generation = request;
      const blob = await new Promise((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", 0.95),
      );
      if (generation !== request || !camera.open) return;
      if (!blob) {
        take.disabled = false;
        status.textContent = "Capture impossible. Réessayez.";
        return;
      }
      const file = new File([blob], "carte-camera.jpg", { type: "image/jpeg" });
      guides.set(file, guideRect(video.videoWidth, video.videoHeight));
      camera.close();
      callback(file);
    });
    await start();
  }
  window.addEventListener("pagehide", stopCamera);
  // Wrapping only pictures leaves edition choices and form actions separate.
  new MutationObserver(enhance).observe(document.body, {
    childList: true,
    subtree: true,
  });
  enhance();
  return Object.freeze({ zoomButton, capture, photoHeaders });
})();
