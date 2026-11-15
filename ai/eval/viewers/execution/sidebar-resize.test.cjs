"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const {mount} = require("./sidebar-resize.js");

function fixture({viewport = 1440, available = viewport, initial = 256} = {}) {
  class Target {
    listeners = new Map();
    addEventListener(type, listener) {
      if (!this.listeners.has(type)) this.listeners.set(type, new Set());
      this.listeners.get(type).add(listener);
    }
    removeEventListener(type, listener) { this.listeners.get(type)?.delete(listener); }
    emit(type, values = {}) {
      const event = {pointerId: 1, button: 0, isPrimary: true, clientX: 256,
        defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...values};
      for (const listener of this.listeners.get(type) || []) listener(event);
      return event;
    }
  }
  const application = new Target(), sidebar = new Target(), handle = new Target(), view = new Target();
  const css = new Map(), attributes = new Map(), classes = new Set(), captures = new Set();
  application.width = available;
  application.getBoundingClientRect = () => ({width: application.width});
  application.style = {getPropertyValue: key => css.get(key) || "", setProperty: (key, value) => css.set(key, value)};
  application.classList = {add: key => classes.add(key), remove: key => classes.delete(key), contains: key => classes.has(key)};
  sidebar.getBoundingClientRect = () => ({width: Number.parseFloat(css.get("--sidebar-width")) || initial});
  handle.setAttribute = (key, value) => attributes.set(key, value);
  handle.getAttribute = key => attributes.get(key);
  handle.setPointerCapture = id => captures.add(id);
  handle.hasPointerCapture = id => captures.has(id);
  handle.releasePointerCapture = id => { captures.delete(id); handle.emit("lostpointercapture", {pointerId: id}); };
  handle.focus = () => { handle.focused = true; };
  view.innerWidth = viewport;
  view.ResizeObserver = class {
    constructor(callback) { view.observer = this; this.callback = callback; }
    observe(target) { this.target = target; }
    disconnect() { this.disconnected = true; }
  };
  const document = {defaultView: view, getElementById: id => ({application, sidebar, "sidebar-resizer": handle})[id]};
  const controller = mount(document);
  return {application, sidebar, handle, view, controller, width: () => Number.parseFloat(css.get("--sidebar-width"))};
}

test("primary dragging uses the measured starting width and clamps at both limits", () => {
  const f = fixture({initial: 280});
  assert.equal(f.width(), 280);
  for (const values of [{button: 2}, {isPrimary: false}]) {
    assert.equal(f.handle.emit("pointerdown", values).defaultPrevented, false);
    assert.equal(f.handle.hasPointerCapture(1), false);
  }
  assert.equal(f.handle.emit("pointerdown").defaultPrevented, true);
  assert.equal(f.handle.hasPointerCapture(1), true);
  assert.equal(f.handle.focused, true);
  assert.equal(f.application.classList.contains("is-resizing-sidebar"), true);
  f.handle.emit("pointermove", {pointerId: 2, clientX: 400});
  assert.equal(f.width(), 280);
  f.handle.emit("pointermove", {clientX: 306});
  assert.equal(f.width(), 330);
  f.handle.emit("pointermove", {clientX: 1000});
  assert.equal(f.width(), 520);
  f.handle.emit("pointermove", {clientX: 0});
  assert.equal(f.width(), 220);
  f.handle.emit("pointerup");
  assert.equal(f.handle.hasPointerCapture(1), false);
  assert.equal(f.application.classList.contains("is-resizing-sidebar"), false);
  f.handle.emit("pointermove", {clientX: 400});
  assert.equal(f.width(), 220);
});

test("cancel and lost capture stop resizing and allow another drag", () => {
  for (const type of ["pointercancel", "lostpointercapture"]) {
    const f = fixture();
    f.handle.emit("pointerdown");
    f.handle.emit(type);
    assert.equal(f.application.classList.contains("is-resizing-sidebar"), false);
    assert.equal(f.handle.hasPointerCapture(1), false);
    f.handle.emit("pointermove", {clientX: 400});
    assert.equal(f.width(), 256);
    f.handle.emit("pointerdown", {pointerId: 2});
    f.handle.emit("pointermove", {pointerId: 2, clientX: 300});
    assert.equal(f.width(), 300);
  }
});

test("keyboard resizing exposes the current width and container limits to assistive technology", () => {
  const f = fixture({available: 900.9});
  assert.equal(f.handle.emit("keydown", {key: "ArrowRight"}).defaultPrevented, true);
  assert.equal(f.width(), 266);
  f.handle.emit("keydown", {key: "ArrowLeft"});
  assert.equal(f.width(), 256);
  f.handle.emit("keydown", {key: "End"});
  assert.equal(f.width(), 412);
  assert.equal(f.handle.getAttribute("aria-valuemin"), "220");
  assert.equal(f.handle.getAttribute("aria-valuemax"), "412");
  assert.equal(f.handle.getAttribute("aria-valuenow"), "412");
  assert.equal(f.handle.getAttribute("aria-valuetext"), "412픽셀");
  f.handle.emit("keydown", {key: "Home"});
  f.handle.emit("keydown", {key: "ArrowLeft"});
  assert.equal(f.width(), 220);
  assert.equal(f.handle.emit("keydown", {key: "Tab"}).defaultPrevented, false);
  assert.equal(f.handle.emit("keydown", {key: "ArrowRight", ctrlKey: true}).defaultPrevented, false);
  assert.equal(f.width(), 220);
});

test("container resize clamps the width and switching to mobile ends the active drag", () => {
  const f = fixture();
  f.handle.emit("keydown", {key: "End"});
  f.application.width = 900;
  f.view.observer.callback();
  assert.equal(f.width(), 412);
  f.handle.emit("pointerdown");
  f.view.innerWidth = 760;
  f.view.emit("resize");
  assert.equal(f.handle.hasPointerCapture(1), false);
  assert.equal(f.application.classList.contains("is-resizing-sidebar"), false);
  assert.equal(f.handle.tabIndex, -1);
  assert.equal(f.handle.getAttribute("aria-disabled"), "true");
  assert.equal(f.handle.emit("keydown", {key: "Home"}).defaultPrevented, false);
  assert.equal(f.handle.emit("pointerdown").defaultPrevented, false);
  assert.equal(f.width(), 412);
  f.view.innerWidth = 800; f.application.width = 800;
  f.view.emit("resize");
  assert.equal(f.width(), 312);
  assert.equal(f.handle.tabIndex, 0);
  assert.equal(f.handle.getAttribute("aria-disabled"), "false");
});

test("an initially hidden or mobile layout is measured only once desktop content becomes visible", () => {
  for (const options of [{available: 0}, {viewport: 390}]) {
    const f = fixture({...options, initial: 280});
    assert.equal(Number.isNaN(f.width()), true);
    f.application.width = 1440; f.view.innerWidth = 1440;
    f.view.observer.callback();
    assert.equal(f.width(), 280);
  }
});

test("destroy releases capture and removes event and layout observers", () => {
  const f = fixture();
  f.handle.emit("pointerdown");
  f.controller.destroy();
  assert.equal(f.handle.hasPointerCapture(1), false);
  assert.equal(f.application.classList.contains("is-resizing-sidebar"), false);
  assert.equal(f.view.observer.disconnected, true);
  f.handle.emit("keydown", {key: "End"});
  f.handle.emit("pointerdown");
  f.application.width = 800; f.view.emit("resize");
  assert.equal(f.width(), 256);
  assert.equal(f.handle.hasPointerCapture(1), false);
});
