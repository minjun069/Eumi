/* DOM 부품: 텍스트는 textContent로 넣고, 산출물 HTML은 격리된 iframe에 표시합니다. */
"use strict";

globalThis.ReportUI = (() => {
  const $ = (id) => document.getElementById(id);
  const format = (value) =>
    ReportData.numeric(value)
      ? value.toLocaleString("ko-KR", { maximumFractionDigits: 2 })
      : "미기록";
  const seconds = (value) =>
    ReportData.numeric(value) ? format(value) + "초" : "미기록";
  const text = (value) =>
    value === undefined
      ? "미기록"
      : typeof value === "string"
        ? value
        : JSON.stringify(value, null, 2);

  function el(tag, className = "", content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  }

  function button(label, onClick, className = "") {
    const node = el("button", className, label);
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
  }

  function badge(label, tone = "") {
    return el("span", "badge " + tone, label);
  }

  function status(value) {
    const tone = ["completed", "success"].includes(value)
      ? "good"
      : ["failed", "error"].includes(value)
        ? "bad"
        : "neutral";
    return badge(ReportData.statuses[value] || value || "상태 미기록", tone);
  }

  function card(title, description, className = "") {
    const node = el("article", "card " + className);
    if (title) node.append(el("h3", "", title));
    if (description) node.append(el("p", "hint", description));
    return node;
  }

  function empty(message) {
    return el("p", "empty", message);
  }

  // 큰 State·HTTP 본문은 사용자가 펼칠 때 DOM을 만듭니다.
  function details(title, build, open = false) {
    const node = el("details", "disclosure");
    node.append(el("summary", "", title));
    let built = false;
    function ensureContent() {
      if (built) return;
      const body = el("div", "disclosure-body");
      body.append(build());
      node.append(body);
      built = true;
    }
    node.addEventListener("toggle", () => {
      if (node.open) ensureContent();
    });
    if (open) ensureContent();
    node.open = open;
    return node;
  }

  let toastTimer;
  function toast(message) {
    clearTimeout(toastTimer);
    $("toast").textContent = message;
    $("toast").hidden = false;
    toastTimer = setTimeout(() => {
      $("toast").hidden = true;
    }, 3000);
  }

  function code(value, className = "") {
    const wrap = el("div", "code-block " + className);
    const content = text(value);
    const pre = el("pre", "", content);
    pre.tabIndex = 0;
    const actions = el("div", "code-actions");
    actions.append(
      button(
        "원문 복사",
        async () => {
          try {
            await navigator.clipboard.writeText(content);
            toast("원문을 복사했습니다.");
          } catch {
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(pre);
            selection.removeAllRanges();
            selection.addRange(range);
            toast("원문을 선택했습니다. Ctrl+C로 복사하세요.");
          }
        },
        "text-button",
      ),
    );
    actions.append(
      button(
        "전체 펼치기",
        (event) => {
          const expanded = wrap.classList.toggle("expanded");
          event.currentTarget.textContent = expanded
            ? "높이 줄이기"
            : "전체 펼치기";
          event.currentTarget.setAttribute("aria-pressed", String(expanded));
        },
        "text-button",
      ),
    );
    wrap.append(actions, pre);
    return wrap;
  }

  function json(title, value, open = false) {
    return details(title, () => code(value), open);
  }

  function table(headers, rows, caption) {
    const wrap = el("div", "table-wrap");
    wrap.tabIndex = 0;
    const node = el("table");
    if (caption) node.append(el("caption", "visually-hidden", caption));
    const head = el("thead");
    const heading = el("tr");
    for (const label of headers) {
      const cell = el("th", "", label);
      cell.scope = "col";
      heading.append(cell);
    }
    head.append(heading);
    const body = el("tbody");
    for (const row of rows) {
      const line = el("tr");
      for (const value of row) {
        const cell = el("td");
        if (value instanceof Node) cell.append(value);
        else cell.textContent = value == null ? "미기록" : String(value);
        line.append(cell);
      }
      body.append(line);
    }
    node.append(head, body);
    wrap.append(node);
    return wrap;
  }

  function escapeHtml(value) {
    return String(value).replace(
      /[&<>"']/g,
      (char) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[char],
    );
  }

  function inline(value) {
    return escapeHtml(value)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function markdown(value) {
    const root = el("div", "prose");
    const lines = text(value).split("\n");
    const cells = (line) =>
      line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim());
    let index = 0;
    while (index < lines.length) {
      const line = lines[index++];
      if (line.trim().startsWith("```")) {
        const block = [];
        while (index < lines.length && !lines[index].trim().startsWith("```"))
          block.push(lines[index++]);
        index++;
        root.append(code(block.join("\n")));
      } else if (
        line.includes("|") &&
        /^\s*\|?\s*:?-{3,}/.test(lines[index] || "")
      ) {
        index++;
        const rows = [];
        while (index < lines.length && lines[index].includes("|"))
          rows.push(cells(lines[index++]));
        root.append(table(cells(line), rows));
      } else if (/^\s*[-*]\s+/.test(line)) {
        const list = el("ul");
        let item = line;
        do {
          const li = el("li");
          li.innerHTML = inline(item.replace(/^\s*[-*]\s+/, ""));
          list.append(li);
          item = lines[index];
          if (!/^\s*[-*]\s+/.test(item || "")) break;
          index++;
        } while (index <= lines.length);
        root.append(list);
      } else if (line.trim()) {
        const heading = line.match(/^(#{1,4})\s+(.*)$/);
        const paragraph = el(heading ? "h4" : "p");
        paragraph.innerHTML = inline(heading ? heading[2] : line);
        root.append(paragraph);
      }
    }
    return root;
  }

  function safeArtifactHtml(source) {
    const doc = new DOMParser().parseFromString(String(source), "text/html");
    const allowed = new Set(
      "html head body title meta style div span p h1 h2 h3 h4 h5 strong b em i ul ol li table thead tbody tfoot tr th td caption details summary br hr pre code section article header footer main svg g rect path text tspan desc line polyline polygon circle ellipse defs clippath".split(
        " ",
      ),
    );
    const attrs = new Set(
      "class id title lang dir role aria-label aria-labelledby aria-hidden scope colspan rowspan open style xmlns viewbox width height x y x1 x2 y1 y2 cx cy r rx ry d points fill stroke stroke-width opacity fill-opacity stroke-opacity font-size font-family font-weight text-anchor dominant-baseline transform clip-path preserveaspectratio".split(
        " ",
      ),
    );
    for (const node of [...doc.querySelectorAll("*")]) {
      if (!allowed.has(node.localName.toLowerCase())) {
        node.remove();
        continue;
      }
      for (const attr of [...node.attributes]) {
        if (
          !attrs.has(attr.name.toLowerCase()) ||
          /url\s*\(|@import|expression\s*\(/i.test(attr.value)
        ) {
          node.removeAttribute(attr.name);
        }
      }
      if (node.localName === "style") {
        node.textContent = node.textContent
          .replace(/@import[^;]*;/gi, "")
          .replace(/url\s*\([^)]*\)/gi, "none");
      }
    }
    const policy = doc.createElement("meta");
    policy.httpEquiv = "Content-Security-Policy";
    policy.content =
      "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'";
    doc.head.prepend(policy);
    return "<!doctype html>" + doc.documentElement.outerHTML;
  }

  function artifact(value, index) {
    const root = card(`산출물 ${index + 1} · ${value.type || "유형 미기록"}`);
    if (value.data?.mime_type === "text/html") {
      const frame = el("iframe", "artifact-frame");
      frame.title = `산출물 ${index + 1} 미리보기`;
      frame.setAttribute("sandbox", "");
      frame.referrerPolicy = "no-referrer";
      frame.srcdoc = safeArtifactHtml(value.data.content);
      root.append(
        el("p", "hint", "스크립트와 외부 요청을 차단한 미리보기입니다."),
        frame,
      );
    } else if (value.data?.dataset?.rows) {
      const dataset = value.data.dataset;
      const keys = (dataset.columns || []).map((column) => column.name);
      root.append(
        table(
          keys,
          dataset.rows
            .slice(0, 200)
            .map((row) => keys.map((key) => text(row[key]))),
        ),
      );
      if (dataset.rows.length > 200)
        root.append(
          el(
            "p",
            "hint",
            "처음 200행 표시 · 전체 값은 아래 원본에서 확인하세요.",
          ),
        );
    }
    root.append(json("산출물 원본 JSON", value));
    return root;
  }

  const stateNames = {
    request: "작업 요청",
    messages: "메시지",
    results: "누적 작업 결과",
    response: "공개 응답",
    execution: "실행 정보",
  };

  function stateFields(value) {
    const root = el("div", "state-fields");
    if (!value) return empty("이 시점의 State는 기록되지 않았습니다.");
    for (const [key, content] of Object.entries(value)) {
      const count = Array.isArray(content) ? ` · ${content.length}개` : "";
      root.append(json(`${stateNames[key] || key} (${key})${count}`, content));
    }
    if (!root.children.length) root.append(empty("변경 필드가 없습니다."));
    return root;
  }

  return {
    $,
    el,
    button,
    badge,
    status,
    card,
    empty,
    details,
    code,
    json,
    table,
    markdown,
    artifact,
    stateFields,
    format,
    seconds,
    text,
    toast,
  };
})();
