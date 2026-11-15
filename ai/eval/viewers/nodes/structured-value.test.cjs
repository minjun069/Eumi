"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const {render} = require("./structured-value.js");

test("unknown keys and values retain their source order without changing the input", () => {
  const value = {unrecognized: "first", nested: {z: 8, a: "last"}, records: [{item: "one"}, {item: "two"}]};
  const before = structuredClone(value);
  Object.freeze(value.nested); Object.freeze(value.records[0]); Object.freeze(value.records[1]);
  Object.freeze(value.records); Object.freeze(value);
  const html = render(value);
  assert.deepEqual(value, before);
  const ordered = ["unrecognized", "first", "nested", '>z<', '>8<', '>a<', "last", "records", "one", "two"];
  let previous = -1;
  for (const text of ordered) {
    const position = html.indexOf(text, previous + 1);
    assert.ok(position > previous, `missing or reordered ${text}`);
    previous = position;
  }
  assert.match(html, /<th class="value-key-cell" scope="row" aria-label="\$\[&quot;unrecognized&quot;\]"><code class="value-key"[^>]*>unrecognized/);
});

test("missing, null, false, zero, strings and empty containers stay distinguishable", () => {
  const html = render({missing: undefined, nothing: null, flag: false, count: 0, text: "0", blank: "", array: [], object: {}, "": -0});
  assert.match(html, /data-value-type="undefined">미제공/);
  assert.match(html, /data-value-type="null">null/);
  assert.match(html, /data-value-type="boolean">false/);
  assert.match(html, /data-value-type="number">0/);
  assert.match(html, /data-value-type="string">0/);
  assert.match(html, /data-value-type="string">빈 문자열/);
  assert.match(html, /data-value-type="array">빈 배열 \[\]/);
  assert.match(html, /data-value-type="object">빈 객체 \{\}/);
  assert.match(html, /빈 키 ""/);
  assert.match(html, /data-value-type="number">-0/);
});

test("heterogeneous arrays keep every index and object field in one flat table", () => {
  const html = render(["first", {different: true}, [null, 5], false, {}, []]);
  assert.match(html, /^<div class="structured-value"><table class="value-table" aria-label="배열 항목과 값">/);
  for (let index = 0; index < 6; index++) assert.ok(html.includes(`>[${index}]</code>`));
  assert.match(html, /\[1\]<\/code><span class="value-meta" data-value-type="object">객체 · 1개 항목/);
  assert.match(html, /aria-label="\$\[1\]\[&quot;different&quot;\]"/);
  assert.match(html, /\[2\]<\/code><span class="value-meta" data-value-type="array">배열 · 2개 항목/);
  assert.ok(html.indexOf("first") < html.indexOf("different"));
  assert.ok(html.indexOf("different") < html.indexOf('data-value-type="null"'));
  assert.equal((html.match(/<table\b/g) || []).length, 1);
});

test("all descendants are visible with metadata beside each group name", () => {
  const html = render({shallow: {deeper: [{last: "retained"}]}});
  assert.doesNotMatch(html, /<details\b|<summary\b|<caption\b|hidden\b|value-branch|value-item/);
  assert.equal((html.match(/<table\b/g) || []).length, 1);
  assert.match(html, />shallow<\/code><span class="value-meta" data-value-type="object">객체 · 1개 항목/);
  assert.match(html, /value-group-row value-depth-0/);
  assert.match(html, /value-group-row value-depth-1/);
  assert.match(html, /value-group-row value-depth-2/);
  assert.match(html, /value-leaf-row value-depth-3/);
  assert.match(html, /aria-label="\$\[&quot;shallow&quot;\]\[&quot;deeper&quot;\]\[0\]\[&quot;last&quot;\]"/);
  assert.ok(html.includes('data-value-type="string">retained</span>'));
});

test("deeply nested values cap indentation while retaining full paths and every leaf", () => {
  let value = {last: "deep-tail"};
  for (let index = 0; index < 40; index++) value = {child: value};
  const html = render(value);
  assert.equal((html.match(/value-group-row/g) || []).length, 40);
  assert.equal((html.match(/value-leaf-row/g) || []).length, 1);
  assert.match(html, /value-leaf-row value-depth-6/);
  assert.doesNotMatch(html, /value-depth-(?:[7-9]|\d{2})\b/);
  assert.ok(html.includes("deep-tail"));
  assert.ok(html.includes("$" + "[&quot;child&quot;]".repeat(40) + "[&quot;last&quot;]"));
});

test("root primitives and empty containers remain compact without table metadata", () => {
  for (const [value, expected] of [[null, "null"], [false, "false"], [0, "0"], ["", "빈 문자열"], [[], "빈 배열 []"], [{}, "빈 객체 {}"], [undefined, "미제공"]]) {
    const html = render(value);
    assert.ok(html.includes(expected));
    assert.doesNotMatch(html, /<table\b|value-meta|<details\b/);
  }
});

test("HTML in keys and strings is escaped and URLs are never made interactive", () => {
  const html = render({['<img src=x onerror="bad()">']: '<script>alert("bad")</script> & \'quote\'', url: "javascript:alert(1)"});
  assert.doesNotMatch(html, /<img|<script|<a\b|href=|onclick=/);
  assert.ok(html.includes("&lt;img src=x onerror=&quot;bad()&quot;&gt;"));
  assert.ok(html.includes("&lt;script&gt;alert(&quot;bad&quot;)&lt;/script&gt; &amp; &#39;quote&#39;"));
  assert.ok(html.includes("javascript:alert(1)"));
});

test("long multiline values keep all whitespace and their final content", () => {
  const value = "  leading\n\t" + "가나다 long_token_".repeat(4000) + "\n  final-tail  ";
  const html = render({message: value});
  assert.ok(html.includes(value));
  assert.ok(html.includes('<span class="value-text" data-value-type="string">  leading\n\t'));
  assert.ok(html.includes("\n  final-tail  </span>"));
});

test("JSON object and array strings gain readable indentation at the root and inside table cells", () => {
  const source = '{"target":"public.region_result","filters":[{"field":"month","values":[1,2]}],"empty":{}}';
  const expected = JSON.stringify(JSON.parse(source), null, 2).replaceAll('"', "&quot;");
  for (const value of [source, {arguments_json: source}, [{nested: source}]]) {
    const before = structuredClone(value), html = render(value);
    assert.ok(html.includes(expected));
    assert.match(html, /class="value-text value-json" data-value-type="string"/);
    assert.deepEqual(value, before);
  }
  const array = '[1,{"enabled":true},[]]';
  assert.ok(render(array).includes(JSON.stringify(JSON.parse(array), null, 2).replaceAll('"', "&quot;")));
});

test("JSON formatting preserves original number tokens, duplicate keys, escapes and HTML safety", () => {
  const source = '{"large":900719925474099312345,"minus":-0,"duplicate":1,"duplicate":2,"exponent":1e+003,"escaped":"\\u0061 \\n \\"","html":"<script>&</script>"}';
  const value = Object.freeze({arguments_json: source}), html = render(value);
  assert.ok(html.includes('\n  &quot;large&quot;: 900719925474099312345,'));
  assert.ok(html.includes('\n  &quot;minus&quot;: -0,'));
  assert.ok(html.includes('\n  &quot;duplicate&quot;: 1,\n  &quot;duplicate&quot;: 2,'));
  assert.ok(html.includes('\n  &quot;exponent&quot;: 1e+003,'));
  assert.ok(html.includes('&quot;escaped&quot;: &quot;\\u0061 \\n \\&quot;&quot;,'));
  assert.ok(html.includes('&quot;html&quot;: &quot;&lt;script&gt;&amp;&lt;/script&gt;&quot;'));
  assert.doesNotMatch(html, /<script>/);
  assert.equal(value.arguments_json, source);
});

test("non-JSON and malformed JSON strings retain their original whitespace and content", () => {
  for (const source of [' {not JSON} ', '{"value":1,}', '[1, 2', '```json\n{"value":1}\n```', '  123  ', '"quoted"', '{"value":NaN}', '\u00a0{"value":1}']) {
    const html = render({value: source});
    assert.doesNotMatch(html, /value-json/);
    assert.ok(html.includes(source.replaceAll('"', "&quot;")));
  }
});

test("the browser global and CommonJS expose the same rendering behavior", () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(require.resolve("./structured-value.js"), "utf8"), context);
  assert.equal(typeof context.NodeValues.render, "function");
  assert.equal(context.NodeValues.render({value: false}), render({value: false}));
});
