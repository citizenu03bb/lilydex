/* Shared photo mechanics. The caller owns the image URL, labels and dialogue. */
"use strict";
window.PhotoZoom = (() => {
  function mount({ frame, image, range, output, reset, minus, plus,
    onChange = () => {}, formatPercent = (percent) => `${percent} %` }) {
    let zoom = 1, pan = null, destroyed = false;
    const listeners = [];
    const originalWidth = image.style.width;
    const hadFrameClass = frame.classList.contains("photo-zoom-frame");
    const hadImageClass = image.classList.contains("photo-zoom-image");
    frame.classList.add("photo-zoom-frame");
    image.classList.add("photo-zoom-image");
    range.min = "1";
    range.max = Number.parseFloat(range.max) >= 1 ? range.max : "4";
    range.step = Number.parseFloat(range.step) > 0 ? range.step : "0.25";
    output.setAttribute("role", "status");
    output.setAttribute("aria-live", "polite");
    output.setAttribute("aria-atomic", "true");
    const listen = (target, name, listener) => {
      if (!target) return;
      target.addEventListener(name, listener);
      listeners.push(() => target.removeEventListener(name, listener));
    };
    const update = () => {
      if (destroyed) return;
      const width = frame.clientWidth;
      const height = Number.parseFloat(getComputedStyle(frame).maxHeight);
      const fitted = image.naturalWidth && image.naturalHeight && height > 0
        ? Math.min(width, height * image.naturalWidth / image.naturalHeight)
        : width;
      if (fitted > 0) image.style.width = `${fitted * zoom}px`;
      range.value = String(zoom);
      const percent = 100 * zoom;
      const text = formatPercent(percent);
      output.textContent = text;
      range.setAttribute("aria-valuetext", text);
      frame.classList.toggle("is-zoomed", zoom > 1);
      if (minus) minus.disabled = zoom <= 1;
      if (plus) plus.disabled = zoom >= Number(range.max);
      onChange({ zoom, percent });
    };
    function endPan(event) {
      if (!pan || (event && event.pointerId !== pan.id)) return;
      const id = pan.id;
      pan = null;
      frame.classList.remove("is-panning");
      try {
        if (frame.hasPointerCapture(id)) frame.releasePointerCapture(id);
      } catch { /* The frame may have left the document during navigation. */ }
    }
    function setZoom(value) {
      if (destroyed) return;
      const numeric = Number(value);
      const step = Number(range.step), max = Number(range.max);
      const next = Number.isFinite(numeric) ? Math.round((numeric - 1) / step) * step + 1 : 1;
      zoom = Math.min(max, Math.max(1, Number(next.toFixed(4))));
      endPan();
      update();
      if (zoom === 1) frame.scrollTo(0, 0);
    }
    const adjust = () => setZoom(1);
    listen(range, "input", () => setZoom(range.value));
    listen(reset, "click", adjust);
    listen(minus, "click", () => setZoom(zoom - Number(range.step)));
    listen(plus, "click", () => setZoom(zoom + Number(range.step)));
    listen(image, "load", update);
    listen(frame, "keydown", (event) => {
      if (event.target !== frame || zoom <= 1 || event.altKey || event.ctrlKey || event.metaKey) return;
      const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
      const move = moves[event.key];
      if (!move && event.key !== "Home" && event.key !== "End") return;
      event.preventDefault();
      event.stopPropagation();
      const distance = event.shiftKey ? 256 : 64;
      if (move) frame.scrollBy(move[0] * distance, move[1] * distance);
      else frame.scrollTo(event.key === "Home" ? 0 : frame.scrollWidth,
        event.key === "Home" ? 0 : frame.scrollHeight);
    });
    listen(frame, "pointerdown", (event) => {
      // Native touch scrolling keeps browser zoom, inertia and page gestures.
      if (event.pointerType === "touch" || event.isPrimary === false || event.button !== 0 || zoom === 1) return;
      event.preventDefault();
      event.stopPropagation();
      frame.focus({ preventScroll: true });
      pan = { id: event.pointerId, x: event.clientX, y: event.clientY,
        left: frame.scrollLeft, top: frame.scrollTop };
      frame.setPointerCapture(event.pointerId);
      frame.classList.add("is-panning");
    });
    listen(frame, "pointermove", (event) => {
      if (!pan || event.pointerId !== pan.id) return;
      event.preventDefault();
      event.stopPropagation();
      frame.scrollLeft = pan.left + pan.x - event.clientX;
      frame.scrollTop = pan.top + pan.y - event.clientY;
    });
    for (const name of ["pointerup", "pointercancel", "lostpointercapture"])
      listen(frame, name, (event) => {
        if (pan?.id === event.pointerId) event.stopPropagation();
        endPan(event);
      });
    const observer = new ResizeObserver(update);
    observer.observe(frame);
    update();
    return Object.freeze({
      reset: adjust, setZoom,
      get zoom() { return zoom; },
      destroy() {
        if (destroyed) return;
        endPan();
        destroyed = true;
        observer.disconnect();
        listeners.forEach((remove) => remove());
        image.style.width = originalWidth;
        frame.classList.remove("is-zoomed", "is-panning");
        if (!hadFrameClass) frame.classList.remove("photo-zoom-frame");
        if (!hadImageClass) image.classList.remove("photo-zoom-image");
      },
    });
  }
  return Object.freeze({ mount });
})();
