/* Sidebar width is presentation state and never changes evaluation data. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else api.attach(root);
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";

  const MIN_WIDTH = 220, MAX_WIDTH = 480, MOBILE_WIDTH = 760;

  function attach(view) {
    const document = view.document;
    const application = document?.querySelector("#application");
    const sidebar = document?.querySelector("#sidebar");
    const splitter = document?.querySelector("#sidebar-splitter");
    if (!application || !sidebar || !splitter) return null;

    let preferredWidth = null, width = 256, active = null;
    const listeners = [];
    const viewportWidth = () => document.documentElement?.clientWidth || view.innerWidth;
    const mobile = () => viewportWidth() <= MOBILE_WIDTH;
    const maximum = () => Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Math.floor(viewportWidth() * .45)));

    function listen(target, type, handler) {
      target.addEventListener(type, handler);
      listeners.push(() => target.removeEventListener(type, handler));
    }

    function apply(value, remember = false) {
      if (!Number.isFinite(value)) return;
      width = Math.round(Math.max(MIN_WIDTH, Math.min(maximum(), value)));
      if (remember) preferredWidth = width;
      application.style.setProperty("--sidebar-width", `${width}px`);
      splitter.setAttribute("aria-valuemin", String(MIN_WIDTH));
      splitter.setAttribute("aria-valuemax", String(maximum()));
      splitter.setAttribute("aria-valuenow", String(width));
      splitter.setAttribute("aria-valuetext", `사이드바 ${width}px`);
    }

    function stop() {
      if (!active) return;
      const {pointerId} = active;
      active = null;
      application.classList.remove("is-sidebar-resizing");
      if (splitter.hasPointerCapture(pointerId)) splitter.releasePointerCapture(pointerId);
    }

    function layout() {
      stop();
      const isMobile = mobile();
      splitter.hidden = isMobile;
      splitter.inert = isMobile;
      splitter.tabIndex = isMobile ? -1 : 0;
      splitter.setAttribute("aria-disabled", String(isMobile));
      if (!isMobile) apply(preferredWidth ?? (viewportWidth() <= 1200 ? 240 : 256));
    }

    listen(splitter, "pointerdown", event => {
      if (event.button !== 0 || active || mobile()) return;
      event.preventDefault();
      splitter.focus({preventScroll: true});
      splitter.setPointerCapture(event.pointerId);
      active = {pointerId: event.pointerId, offset: event.clientX - application.getBoundingClientRect().left - width};
      application.classList.add("is-sidebar-resizing");
    });
    listen(splitter, "pointermove", event => {
      if (!active || event.pointerId !== active.pointerId) return;
      if (!splitter.isConnected || mobile()) { stop(); return; }
      apply(event.clientX - application.getBoundingClientRect().left - active.offset, true);
    });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
      listen(splitter, type, event => { if (event.pointerId === active?.pointerId) stop(); });
    }
    listen(splitter, "keydown", event => {
      if (mobile() || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      stop();
      apply(event.key === "Home" ? MIN_WIDTH : event.key === "End" ? maximum() : width + (event.key === "ArrowRight" ? 16 : -16), true);
    });
    listen(view, "resize", layout);
    listen(view, "blur", stop);
    layout();

    return {destroy() { stop(); for (const remove of listeners) remove(); }};
  }

  return Object.freeze({attach});
});
