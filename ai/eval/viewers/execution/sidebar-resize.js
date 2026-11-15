/* Resize only the viewer layout; saved evaluation data is never changed. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.ExecutionSidebarResize = api;
    api.mount(root.document, root);
  }
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";
  const MIN_WIDTH = 220, MAX_WIDTH = 520, CONTENT_WIDTH = 488, MOBILE_WIDTH = 760;

  function mount(document, view = document?.defaultView) {
    const application = document?.getElementById("application");
    const sidebar = document?.getElementById("sidebar");
    const handle = document?.getElementById("sidebar-resizer");
    if (!application || !sidebar || !handle || !view) return null;
    let width = null, drag = null;

    function bounds() {
      const available = application.getBoundingClientRect().width;
      if (view.innerWidth <= MOBILE_WIDTH || available <= 0) return null;
      return {min: MIN_WIDTH, max: Math.max(MIN_WIDTH, Math.floor(Math.min(MAX_WIDTH, available - CONTENT_WIDTH)))};
    }
    function setWidth(value, range) {
      width = Math.round(Math.max(range.min, Math.min(range.max, value)));
      const cssWidth = `${width}px`;
      if (application.style.getPropertyValue("--sidebar-width") !== cssWidth) {
        application.style.setProperty("--sidebar-width", cssWidth);
      }
      handle.setAttribute("aria-valuemin", String(range.min));
      handle.setAttribute("aria-valuemax", String(range.max));
      handle.setAttribute("aria-valuenow", String(width));
      handle.setAttribute("aria-valuetext", `${width}픽셀`);
    }
    function finish(event) {
      if (!drag || (event && event.pointerId !== drag.pointerId)) return;
      const pointerId = drag.pointerId;
      drag = null;
      application.classList.remove("is-resizing-sidebar");
      if (handle.hasPointerCapture(pointerId)) handle.releasePointerCapture(pointerId);
    }
    function sync() {
      const range = bounds();
      handle.setAttribute("aria-disabled", String(!range));
      handle.tabIndex = range ? 0 : -1;
      if (!range) { finish(); return; }
      setWidth(width ?? sidebar.getBoundingClientRect().width, range);
    }
    function pointerDown(event) {
      if (event.button !== 0 || event.isPrimary === false || drag) return;
      const range = bounds();
      if (!range) return;
      event.preventDefault();
      setWidth(width ?? sidebar.getBoundingClientRect().width, range);
      drag = {pointerId: event.pointerId, startX: event.clientX, startWidth: width};
      handle.setPointerCapture(event.pointerId);
      handle.focus({preventScroll: true});
      application.classList.add("is-resizing-sidebar");
    }
    function pointerMove(event) {
      if (!drag || event.pointerId !== drag.pointerId) return;
      const range = bounds();
      if (!range) { sync(); return; }
      event.preventDefault();
      setWidth(drag.startWidth + event.clientX - drag.startX, range);
    }
    function keyDown(event) {
      const range = bounds();
      if (!range || event.altKey || event.ctrlKey || event.metaKey) return;
      const current = width ?? sidebar.getBoundingClientRect().width;
      const next = {ArrowLeft: current - 10, ArrowRight: current + 10, Home: range.min, End: range.max}[event.key];
      if (next === undefined) return;
      event.preventDefault();
      finish();
      setWidth(next, range);
    }

    const listeners = {pointerdown: pointerDown, pointermove: pointerMove, pointerup: finish,
      pointercancel: finish, lostpointercapture: finish, keydown: keyDown};
    for (const [type, listener] of Object.entries(listeners)) handle.addEventListener(type, listener);
    view.addEventListener("resize", sync);
    const observer = view.ResizeObserver ? new view.ResizeObserver(sync) : null;
    observer?.observe(application);
    sync();
    return {
      sync,
      destroy() {
        finish();
        observer?.disconnect();
        view.removeEventListener("resize", sync);
        for (const [type, listener] of Object.entries(listeners)) handle.removeEventListener(type, listener);
      },
    };
  }
  return {mount};
});
