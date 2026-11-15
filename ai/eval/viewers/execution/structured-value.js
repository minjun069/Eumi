/* Read-only presentation of stored JSON values. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ExecutionValues = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";

  const escape = value => String(value).replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
  const empty = (type, label) => `<span class="value-empty" data-value-type="${type}">${label}</span>`;
  const compound = value => value !== null && typeof value === "object";

  function scalar(value) {
    if (value === undefined) return empty("undefined", "미제공");
    if (value === null) return '<code class="value-scalar" data-value-type="null">null</code>';
    if (compound(value)) return Array.isArray(value) ? empty("array", "빈 배열 []") : empty("object", "빈 객체 {}");
    if (typeof value === "string") {
      return value === "" ? empty("string", "빈 문자열") : `<span class="value-text" data-value-type="string">${escape(value)}</span>`;
    }
    const text = Object.is(value, -0) ? "-0" : String(value);
    return `<code class="value-scalar" data-value-type="${escape(typeof value)}">${escape(text)}</code>`;
  }

  function children(value, depth, path) {
    return Object.entries(value).map(([key, item]) => ({
      value: item, depth, key: Array.isArray(value) ? `[${key}]` : key,
      path: path + (Array.isArray(value) ? `[${key}]` : `[${JSON.stringify(key)}]`),
    }));
  }

  function render(value) {
    if (!compound(value) || !Object.keys(value).length) return `<div class="structured-value">${scalar(value)}</div>`;
    const pending = children(value, 0, "$").reverse(), rows = [];
    while (pending.length) {
      const item = pending.pop();
      const nested = compound(item.value) ? children(item.value, item.depth + 1, item.path) : [];
      const label = `<code class="value-key" title="${escape(item.path)}">${item.key === "" ? '<span class="value-empty">빈 키 ""</span>' : escape(item.key)}</code>`;
      const depth = `value-depth-${Math.min(item.depth, 6)}`;
      if (nested.length) {
        const array = Array.isArray(item.value);
        rows.push(`<tr class="value-group-row ${depth}"><th colspan="2" scope="row" aria-label="${escape(item.path)}">${label}<span class="value-meta" data-value-type="${array ? "array" : "object"}">${array ? "배열" : "객체"} · ${nested.length}개 항목</span></th></tr>`);
        for (let index = nested.length - 1; index >= 0; index--) pending.push(nested[index]);
      } else {
        rows.push(`<tr class="value-leaf-row ${depth}"><th class="value-key-cell" scope="row" aria-label="${escape(item.path)}">${label}</th><td>${scalar(item.value)}</td></tr>`);
      }
    }
    return `<div class="structured-value"><table class="value-table" aria-label="${Array.isArray(value) ? "배열" : "객체"} 항목과 값"><colgroup><col class="value-key-column"><col></colgroup><tbody>${rows.join("")}</tbody></table></div>`;
  }

  return {render};
});
