/* Read-only presentation of stored JSON values. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.NodeValues = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";

  const escape = value => String(value).replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
  const empty = (type, label) => `<span class="value-empty" data-value-type="${type}">${label}</span>`;
  const compound = value => value !== null && typeof value === "object";

  function formattedJSON(value) {
    if (!/^[\x20\t\r\n]*[\[{]/.test(value)) return null;
    try { JSON.parse(value); } catch { return null; }
    // Validate with the parser, then retain original tokens, including duplicate keys and exact numbers.
    const tokens = value.match(/"(?:\\.|[^"\\])*"|[{}\[\],:]|[^\s{}\[\],:]+/g), output = [];
    let depth = 0;
    const newline = () => "\n" + "  ".repeat(depth);
    for (let index = 0; index < tokens.length; index++) {
      const token = tokens[index];
      if (token === "{" || token === "[") {
        output.push(token);
        depth++;
        if (tokens[index + 1] !== "}" && tokens[index + 1] !== "]") output.push(newline());
      } else if (token === "}" || token === "]") {
        depth--;
        if (tokens[index - 1] !== "{" && tokens[index - 1] !== "[") output.push(newline());
        output.push(token);
      } else if (token === ",") output.push(token, newline());
      else if (token === ":") output.push(": ");
      else output.push(token);
    }
    return output.join("");
  }

  function scalar(value) {
    if (value === undefined) return empty("undefined", "미제공");
    if (value === null) return '<code class="value-scalar" data-value-type="null">null</code>';
    if (compound(value)) return Array.isArray(value) ? empty("array", "빈 배열 []") : empty("object", "빈 객체 {}");
    if (typeof value === "string") {
      if (value === "") return empty("string", "빈 문자열");
      const formatted = formattedJSON(value);
      return `<span class="value-text${formatted === null ? "" : " value-json"}" data-value-type="string">${escape(formatted ?? value)}</span>`;
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
