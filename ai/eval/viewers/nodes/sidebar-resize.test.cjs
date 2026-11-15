"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {attach} = require("./sidebar-resize.js");

function eventTarget(extra = {}) {
  const listeners = new Map();
  return {
    ...extra,
    addEventListener(type, handler) { if (!listeners.has(type)) listeners.set(type, new Set()); listeners.get(type).add(handler); },
    removeEventListener(type, handler) { listeners.get(type)?.delete(handler); },
    fire(type, fields = {}) {
      const event = {prevented: false, preventDefault() { this.prevented = true; }, ...fields};
      for (const handler of listeners.get(type) || []) handler(event);
      return event;
    },
  };
}

function harness(initialWidth = 1440) {
  const properties = new Map(), classes = new Set(), attributes = new Map(), captures = new Set();
  const application = {style: {setProperty: (key, value) => properties.set(key, value)},
    classList: {add: name => classes.add(name), remove: name => classes.delete(name)},
    getBoundingClientRect: () => ({left: 30})};
  const splitter = eventTarget({isConnected: true, focused: 0,
    focus() { this.focused++; },
    setAttribute: (key, value) => attributes.set(key, value),
    setPointerCapture: id => captures.add(id), hasPointerCapture: id => captures.has(id),
    releasePointerCapture: id => captures.delete(id)});
  const elements = {"#application": application, "#sidebar": {}, "#sidebar-splitter": splitter};
  const view = eventTarget({innerWidth: initialWidth, document: {
    documentElement: {clientWidth: initialWidth}, querySelector: selector => elements[selector] || null,
  }});
  const controller = attach(view);
  const width = () => Number(properties.get("--sidebar-width")?.replace("px", ""));
  return {view, splitter, controller, width, attributes, captures, classes,
    resize(next) { view.innerWidth = next; view.document.documentElement.clientWidth = next; view.fire("resize"); },
    drag(next, pointerId = 1) {
      const start = width();
      splitter.fire("pointerdown", {button: 0, pointerId, clientX: 30 + start + 4});
      splitter.fire("pointermove", {pointerId, clientX: 30 + next + 4});
      splitter.fire("pointerup", {pointerId});
    },
  };
}

test("default widths and live ARIA limits follow the available desktop viewport", () => {
  const h = harness();
  assert.equal(h.width(), 256);
  assert.equal(h.attributes.get("aria-valuenow"), "256");
  assert.equal(h.attributes.get("aria-valuemin"), "220");
  assert.equal(h.attributes.get("aria-valuemax"), "480");
  assert.equal(h.splitter.hidden, false);
  assert.equal(h.splitter.inert, false);
  h.resize(1100);
  assert.equal(h.width(), 240);
  h.resize(800);
  assert.equal(h.attributes.get("aria-valuemax"), "360");
  assert.equal(h.width(), 240);
});

test("pointer capture preserves the grab offset and ignores other pointers or controls", () => {
  const h = harness();
  assert.equal(h.splitter.fire("pointerdown", {button: 2, pointerId: 3, clientX: 290}).prevented, false);
  assert.equal(h.captures.size, 0);
  h.view.fire("pointerdown", {button: 0, pointerId: 2, clientX: 700});
  assert.equal(h.captures.size, 0);
  const down = h.splitter.fire("pointerdown", {button: 0, pointerId: 1, clientX: 290});
  assert.equal(down.prevented, true);
  assert.equal(h.splitter.focused, 1);
  assert.equal(h.captures.has(1), true);
  assert.equal(h.classes.has("is-sidebar-resizing"), true);
  h.splitter.fire("pointermove", {pointerId: 2, clientX: 500});
  assert.equal(h.width(), 256);
  h.splitter.fire("pointermove", {pointerId: 1, clientX: 334});
  assert.equal(h.width(), 300);
  h.splitter.fire("pointerup", {pointerId: 1});
  assert.equal(h.captures.size, 0);
  assert.equal(h.classes.has("is-sidebar-resizing"), false);
  h.splitter.fire("pointermove", {pointerId: 1, clientX: 450});
  assert.equal(h.width(), 300);
});

test("drag and keyboard respect bounds while preserving the user's width through resize", () => {
  const h = harness();
  h.drag(900);
  assert.equal(h.width(), 480);
  h.resize(800);
  assert.equal(h.width(), 360);
  h.resize(1440);
  assert.equal(h.width(), 480);
  h.drag(100);
  assert.equal(h.width(), 220);
  assert.equal(h.splitter.fire("keydown", {key: "ArrowRight"}).prevented, true);
  assert.equal(h.width(), 236);
  h.splitter.fire("keydown", {key: "ArrowLeft"});
  assert.equal(h.width(), 220);
  h.splitter.fire("keydown", {key: "End"});
  assert.equal(h.width(), 480);
  assert.equal(h.attributes.get("aria-valuetext"), "사이드바 480px");
  h.splitter.fire("keydown", {key: "Home"});
  assert.equal(h.width(), 220);
  assert.equal(h.splitter.fire("keydown", {key: "Tab"}).prevented, false);
});

test("mobile transition stops dragging, disables the handle and restores the selected width", () => {
  const h = harness();
  h.drag(400);
  h.splitter.fire("pointerdown", {button: 0, pointerId: 1, clientX: 434});
  h.resize(760);
  assert.equal(h.captures.size, 0);
  assert.equal(h.classes.size, 0);
  assert.equal(h.splitter.hidden, true);
  assert.equal(h.splitter.inert, true);
  assert.equal(h.splitter.tabIndex, -1);
  assert.equal(h.attributes.get("aria-disabled"), "true");
  h.splitter.fire("pointermove", {pointerId: 1, clientX: 600});
  assert.equal(h.splitter.fire("keydown", {key: "Home"}).prevented, false);
  assert.equal(h.splitter.fire("pointerdown", {button: 0, pointerId: 2, clientX: 300}).prevented, false);
  assert.equal(h.width(), 400);
  h.resize(1440);
  assert.equal(h.width(), 400);
  assert.equal(h.splitter.hidden, false);
  assert.equal(h.splitter.inert, false);
  assert.equal(h.splitter.tabIndex, 0);
});

test("cancellation, lost capture, window blur and destroy release an active drag", () => {
  for (const finish of ["pointercancel", "lostpointercapture", "blur", "destroy"]) {
    const h = harness();
    h.splitter.fire("pointerdown", {button: 0, pointerId: 1, clientX: 290});
    if (finish === "destroy") h.controller.destroy();
    else if (finish === "blur") h.view.fire(finish);
    else h.splitter.fire(finish, {pointerId: 1});
    assert.equal(h.captures.size, 0, finish);
    assert.equal(h.classes.size, 0, finish);
    h.splitter.fire("pointermove", {pointerId: 1, clientX: 440});
    assert.equal(h.width(), 256, finish);
    if (finish === "destroy") {
      h.splitter.fire("keydown", {key: "End"});
      h.resize(1100);
      assert.equal(h.width(), 256);
    }
  }
});

test("the deferred browser entry attaches automatically and absent markup is harmless", () => {
  assert.equal(attach({document: {querySelector: () => null}}), null);
  const h = harness(1100);
  h.controller.destroy();
  vm.runInNewContext(fs.readFileSync(require.resolve("./sidebar-resize.js"), "utf8"), h.view);
  h.splitter.fire("keydown", {key: "ArrowRight"});
  assert.equal(h.width(), 256);
});
