/* 화면 연결과 다섯 영역의 렌더링. 각 render 함수가 HTML의 같은 이름 영역을 담당합니다. */
"use strict";

(() => {
  const D = ReportData;
  const U = ReportUI;
  const { $, el, button, badge, card, empty, details, code, json, table } = U;
  const reports = [];
  let current = 0;
  let section = "overview";
  let inspection;
  let selectedNode;
  let searchIndex = new Map();

  const currentReport = () => reports[current]?.report;
  const reportTitle = (item, index) =>
    item.report.scenario || `실행 ${String(index + 1).padStart(2, "0")}`;
  const nodeTitle = (group) =>
    `${String(group.order).padStart(2, "0")}  ${D.label(group.node.name)}`;

  function tokens(usage, key, traced = true) {
    if (!usage.calls) return traced ? "해당 없음" : "미기록";
    const recorded = usage[key + "Recorded"];
    if (!recorded) return "미기록";
    const suffix =
      recorded < usage.calls ? ` · ${recorded}/${usage.calls}회 기록` : "";
    return U.format(usage[key]) + suffix;
  }

  function ingest(documents) {
    const errors = [];
    let added = 0;
    for (const document of documents) {
      for (const value of Array.isArray(document.value)
        ? document.value
        : [document.value]) {
        try {
          const report = D.normalize(value);
          const id = report.state.execution.run_id;
          const existing = reports.findIndex(
            (item) => id && item.report.state.execution.run_id === id,
          );
          const item = { name: document.name, report };
          if (existing < 0) {
            reports.push(item);
            current = reports.length - 1;
          } else {
            reports[existing] = item;
            current = existing;
          }
          added++;
        } catch (error) {
          errors.push(`${document.name}: ${error.message}`);
        }
      }
    }
    return { errors, added };
  }

  function showSection(name, focus = false) {
    section = name;
    for (const control of $("sections").querySelectorAll("button")) {
      const active = control.dataset.section === name;
      control.setAttribute("aria-pressed", String(active));
      $(control.dataset.section).hidden = !active;
    }
    if (focus) {
      const heading = $(name).querySelector("h2");
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
      $(name).scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }

  function renderSidebar() {
    $("run-count").textContent = reports.length;
    $("runs").replaceChildren();
    reports.forEach((item, index) => {
      const control = button(
        "",
        () => {
          current = index;
          selectedNode = null;
          $("node-search").value = "";
          $("errors-only").checked = false;
          render();
        },
        "run-button",
      );
      control.setAttribute("aria-current", String(index === current));
      const head = el("div", "row");
      control.title = item.name;
      head.append(
        el("strong", "run-name", reportTitle(item, index)),
        U.status(item.report.state.execution.status),
      );
      control.append(
        head,
        el("p", "run-goal", item.report.state.request?.goal || "요청 미기록"),
      );
      control.append(
        el(
          "small",
          "mono muted",
          (item.report.state.execution.run_id || "ID 미기록").slice(0, 12),
        ),
      );
      $("runs").append(control);
    });
  }

  function renderSummary(report) {
    const execution = report.state.execution;
    $("title").textContent = report.scenario
      ? `${report.scenario} 실행 기록`
      : "Agent 실행 기록";
    $("subtitle").textContent = `실행 ID  ${execution.run_id || "미기록"}`;
    const total =
      inspection.models.length || inspection.spans.length
        ? D.sumTokens(inspection.models.map(D.modelTokens))
        : D.sumTokens(
            D.flatten(report.state.results)
              .filter((record) => record.output?.model_usage)
              .map((record) => ({
                input: record.output.model_usage.tokens?.input_tokens,
                output: record.output.model_usage.tokens?.output_tokens,
              })),
          );
    const roots = inspection.spans.filter(
      (span) => !span.parent_id && span.kind === "agent",
    );
    const duration =
      report.elapsed_seconds ??
      (roots.length && roots.every((span) => D.numeric(span.elapsed_seconds))
        ? roots.reduce((sum, span) => sum + span.elapsed_seconds, 0)
        : undefined);
    const values = [
      [
        "실행 상태",
        D.statuses[execution.status] || execution.status,
        `${inspection.groups.length}개 노드 기록`,
      ],
      ["실행 시간", U.seconds(duration), "재개 대기 시간은 제외될 수 있습니다"],
      [
        "입력 토큰",
        tokens(total, "input", inspection.spans.length > 0),
        total.calls
          ? `${total.calls}회 모델 호출 기록 기준`
          : "모델 호출 기록 없음",
      ],
      [
        "출력 토큰",
        tokens(total, "output", inspection.spans.length > 0),
        "미기록 사용량은 합산하지 않습니다",
      ],
    ];
    $("stats").replaceChildren(
      ...values.map(([label, value, hint]) => {
        const block = el("div", "stat");
        block.append(
          el("p", "stat-label", label),
          el("strong", "stat-value", value),
          el("p", "stat-hint", hint),
        );
        return block;
      }),
    );
    $("run-notice").replaceChildren();
    if (report.failure || execution.error) {
      const failure = card(
        "실행 중 오류가 기록되었습니다.",
        null,
        "error-card",
      );
      failure.append(
        json("오류 상세", report.failure || execution.error, true),
      );
      $("run-notice").append(failure);
    }
  }

  // 01. 현재 요청과 공개 응답. request.goal을 사용자 입력 원문으로 바꾸어 표시하지 않습니다.
  function renderOverview(report) {
    const panel = $("overview-content");
    panel.replaceChildren();
    const conversation = D.conversation(report, inspection);
    const input = card(
      "사용자 최초 입력",
      "이번 실행을 시작한 입력 원문",
      "request-card",
    );
    if (conversation.current)
      input.append(
        el("div", "request-text", U.text(conversation.current.content)),
      );
    else
      input.append(
        empty(
          conversation.known
            ? "사용자 입력 없이 시작된 실행입니다. 아래 작업 요청을 확인하세요."
            : "시작 시점의 메시지가 없어 최초 입력을 확인할 수 없습니다.",
        ),
      );
    input.append(
      json("State에 저장된 작업 요청 · request", report.state.request),
    );
    panel.append(input);

    const reply = report.state.response;
    const output = card("Agent 답변", null, "answer-card");
    if (reply) {
      const kinds = {
        final: "최종 응답",
        intermediate: "중간 응답",
        progress: "진행 상황",
        question: "추가 질문",
      };
      output.append(
        badge(kinds[reply.kind] || reply.kind, "accent"),
        U.markdown(reply.content || "내용이 비어 있습니다."),
      );
      output.append(json("공개 응답 원본 · response", reply));
    } else output.append(empty("저장된 공개 응답이 없습니다."));
    panel.append(output);
    (reply?.artifacts || []).forEach((artifact, index) =>
      panel.append(U.artifact(artifact, index)),
    );
    if (report.evaluation) {
      panel.append(
        details("시나리오 검사 결과", () => {
          const body = el("div");
          body.append(
            U.status(report.evaluation.passed ? "success" : "failed"),
          );
          body.append(
            table(
              ["검사 항목", "결과"],
              Object.entries(report.evaluation.checks || {}).map(
                ([name, passed]) => [name, passed ? "통과" : "미통과"],
              ),
            ),
          );
          if (report.evaluation.scope)
            body.append(el("p", "hint", report.evaluation.scope));
          return body;
        }),
      );
    }
  }

  function openNode(id) {
    selectedNode = id;
    $("node-search").value = "";
    $("errors-only").checked = false;
    renderNodeList();
    showSection("nodes", true);
  }

  // 02. 부모 Agent별 실행 순서. 중첩 호출을 한 줄의 직렬 흐름으로 오해하지 않게 분리합니다.
  function renderFlow(report) {
    const panel = $("flow-content");
    panel.replaceChildren();
    const groups = inspection.groups;
    const graph = card(
      "노드 흐름 도식",
      "같은 실행 경로 안의 호출 시작 순서입니다. 하위 Agent는 별도 줄로 표시합니다.",
    );
    if (!groups.length) graph.append(empty("노드 실행 기록이 없습니다."));
    if (groups.some((group) => group.legacy)) {
      graph.append(
        el(
          "p",
          "notice",
          "호출 trace가 없어 연속된 결과 이력을 노드별로 묶었습니다. 실제 노드 호출 수·시간은 확인할 수 없습니다.",
        ),
      );
    }
    const lanes = new Map();
    for (const group of groups) {
      const key = group.legacy ? group.path : group.node.parent_id;
      if (!lanes.has(key)) lanes.set(key, []);
      lanes.get(key).push(group);
    }
    for (const laneGroups of lanes.values()) {
      const lane = el("div", "flow-lane");
      lane.append(el("p", "lane-title", laneGroups[0].path));
      const track = el("ol", "flow-track");
      for (const group of laneGroups) {
        const item = el("li");
        const control = button(
          "",
          () => openNode(group.node.id),
          "flow-node" + (group.hasError ? " has-error" : ""),
        );
        control.append(
          el("span", "eyebrow", `NODE ${String(group.order).padStart(2, "0")}`),
        );
        control.append(
          el("strong", "", D.label(group.node.name)),
          el("code", "muted", group.node.name),
        );
        control.append(
          el("span", "flow-time", U.seconds(group.node.elapsed_seconds)),
        );
        if (group.hasError) control.append(badge("오류 기록", "bad"));
        item.append(control);
        track.append(item);
      }
      lane.append(track);
      graph.append(lane);
    }
    panel.append(graph);
    const metrics = card(
      "노드별 시간·토큰",
      "토큰은 해당 노드가 직접 호출한 모델만 합산합니다. 노드 시간에는 하위 호출이 포함될 수 있어 행별 시간을 더하면 중복됩니다.",
    );
    metrics.append(
      table(
        [
          "노드",
          "실행 경로",
          "시간",
          "모델 호출",
          "입력 토큰",
          "출력 토큰",
          "상태",
        ],
        groups.map((group) => [
          button(nodeTitle(group), () => openNode(group.node.id), "table-link"),
          group.path,
          U.seconds(group.node.elapsed_seconds),
          group.legacy
            ? group.tokens.calls
              ? `${group.tokens.calls}회 기록`
              : "미기록"
            : `${group.tokens.calls}회`,
          tokens(group.tokens, "input", !group.legacy),
          tokens(group.tokens, "output", !group.legacy),
          group.hasError
            ? badge("오류 기록", "bad")
            : U.status(group.node.status),
        ]),
        "노드별 시간과 입력·출력 토큰",
      ),
    );
    panel.append(metrics);
    panel.append(
      json("판단·도구·검증 이력 전체 · results", report.state.results),
    );
    const unowned = inspection.models.filter(
      (model) => !groups.some((group) => group.calls.includes(model)),
    );
    if (unowned.length)
      panel.append(json("노드 연결 정보가 없는 모델 호출", unowned));
  }

  // 03. 노드 선택 → 입력 State → 모델별 프롬프트·반환 → State 변경.
  function renderNodeList() {
    const query = $("node-search").value.trim().toLocaleLowerCase();
    const filtered = inspection.groups.filter(
      (group) =>
        (!$("errors-only").checked || group.hasError) &&
        (!query || searchIndex.get(group.node.id).includes(query)),
    );
    if (!filtered.some((group) => group.node.id === selectedNode))
      selectedNode = filtered[0]?.node.id;
    $("node-count").textContent =
      `${inspection.groups.length}개 노드 · ${filtered.length}개 표시`;
    $("node-list").replaceChildren();
    for (const group of filtered) {
      const control = button(
        "",
        () => {
          selectedNode = group.node.id;
          renderNodeList();
        },
        "node-button",
      );
      control.setAttribute(
        "aria-pressed",
        String(group.node.id === selectedNode),
      );
      control.append(
        el("strong", "", nodeTitle(group)),
        el("small", "mono", group.node.name),
      );
      control.append(
        el(
          "span",
          "muted",
          `${U.seconds(group.node.elapsed_seconds)} · 모델 ${group.legacy && !group.tokens.calls ? "미기록" : group.tokens.calls + "회"}`,
        ),
      );
      if (group.hasError) control.append(badge("오류 기록", "bad"));
      $("node-list").append(control);
    }
    if (!filtered.length)
      $("node-list").append(empty("검색 조건에 맞는 노드가 없습니다."));
    renderNodeDetail();
  }

  function renderModel(span) {
    const root = el("div", "model-detail");
    const usage = D.modelTokens(span);
    const meta = el("div", "model-meta");
    meta.append(
      U.status(span.status),
      el("span", "", U.seconds(span.elapsed_seconds)),
      el(
        "span",
        "",
        `입력 ${U.format(usage.input)} / 출력 ${U.format(usage.output)} 토큰`,
      ),
    );
    root.append(meta);
    const source = D.modelMessages(span);
    root.append(
      el(
        "p",
        "hint",
        source.source + " · 메시지 순서와 원문을 그대로 표시합니다.",
      ),
    );
    if (!source.messages.length)
      root.append(empty("프롬프트가 기록되지 않았습니다."));
    source.messages.forEach((message, index) => {
      const role = D.role(message);
      const title =
        {
          system: "시스템 프롬프트",
          developer: "개발자 프롬프트",
          human: "유저 프롬프트",
          user: "유저 프롬프트",
          assistant: "이전 모델 응답",
          ai: "이전 모델 응답",
          tool: "도구 반환 메시지",
        }[role] || "입력 항목";
      const block = el("section", "prompt-block");
      block.append(
        el("h4", "", `${index + 1}. ${title}`),
        code(D.contentText(message.content ?? message)),
      );
      root.append(block);
    });
    const returned = el("section", "prompt-block returned");
    returned.append(el("h4", "", "모델 반환 결과"));
    returned.append(code(D.modelOutput(span) ?? "반환 결과 미기록"));
    if (span.output?.validated !== undefined)
      returned.append(json("스키마 검증 후 결과", span.output.validated, true));
    if (span.error)
      returned.append(json("호출·스키마 검증 오류", span.error, true));
    root.append(returned);
    root.append(json("응답 스키마", span.input?.response_schema));
    root.append(json("모델 호출 직전 입력 스냅샷", span.input));
    root.append(json("HTTP 요청·응답 및 SDK 원본", span));
    return root;
  }

  function renderStateChanges(node) {
    const root = el("div");
    const update = node.output?.applied_update;
    if (update) {
      root.append(
        el(
          "p",
          "hint",
          "필드별로 실행 전 값과 실행기가 전달한 변경값을 비교합니다. messages는 병합용 변경값이며 최종 메시지 전체가 아닐 수 있습니다.",
        ),
      );
      for (const [key, value] of Object.entries(update)) {
        const before = node.input?.state?.[key];
        const changed = JSON.stringify(before) !== JSON.stringify(value);
        root.append(
          details(`${key} · ${changed ? "변경값 있음" : "동일 값"}`, () => {
            const comparison = el("div", "comparison");
            const left = el("div");
            const right = el("div");
            left.append(el("h4", "", "실행 전"), code(before));
            right.append(el("h4", "", "실행기가 전달한 변경값"), code(value));
            comparison.append(left, right);
            return comparison;
          }),
        );
      }
    } else root.append(empty("실행기가 적용한 변경값은 기록되지 않았습니다."));
    root.append(
      json("노드가 반환한 변경값 · node_update", node.output?.node_update),
    );
    root.append(json("실행기가 전달한 변경값 · applied_update", update));
    if (node.output?.goto)
      root.append(
        el(
          "p",
          "next-node",
          `다음 단계 → ${D.label(node.output.goto === "__end__" ? "종료" : node.output.goto)}`,
        ),
      );
    return root;
  }

  function renderNodeDetail() {
    const panel = $("node-detail");
    panel.replaceChildren();
    const group = inspection.groups.find(
      (item) => item.node.id === selectedNode,
    );
    if (!group) {
      panel.append(empty("확인할 노드를 선택하세요."));
      return;
    }
    const node = group.node;
    const header = card(nodeTitle(group), group.path, "node-heading");
    const meta = el("div", "row");
    meta.append(el("code", "muted", node.name), U.status(node.status));
    header.append(meta);
    if (node.error) header.append(json("노드 오류", node.error, true));
    panel.append(header);

    const state = card(
      "1. 입력 State",
      "노드 실행 직전의 값입니다. 모델에 전송한 프롬프트는 아래 호출별로 확인하세요.",
    );
    state.append(U.stateFields(node.input?.state));
    panel.append(state);
    const models = group.calls.filter((span) => span.kind === "model");
    const modelCard = card(
      "2. 모델 호출",
      "호출을 선택하면 시스템·유저 프롬프트와 모델 반환 결과가 함께 바뀝니다.",
    );
    if (models.length) {
      const picker = el("div", "model-picker");
      picker.setAttribute("aria-label", "모델 호출 선택");
      const content = el("div");
      function selectModel(selected) {
        for (const control of picker.children)
          control.setAttribute(
            "aria-pressed",
            String(control.dataset.id === selected.id),
          );
        content.replaceChildren(renderModel(selected));
      }
      models.forEach((span, index) => {
        const control = button(
          `${index + 1}. ${D.label(span.name)}${span.error ? " · 오류" : ""}`,
          () => selectModel(span),
        );
        control.dataset.id = span.id;
        picker.append(control);
      });
      modelCard.append(picker, content);
      selectModel(models[0]);
    } else
      modelCard.append(
        empty(
          group.legacy
            ? "이 기록에는 모델 호출 시점의 프롬프트가 없습니다."
            : "이 노드의 모델 호출 기록이 없습니다.",
        ),
      );
    panel.append(modelCard);

    const changes = card(
      "3. State 변화",
      "노드 반환값과 실행기가 전달한 변경값을 구분합니다.",
    );
    changes.append(renderStateChanges(node));
    panel.append(changes);
    const calls = group.calls.filter((span) => span.kind !== "model");
    const additional = card("도구 호출·판단 이력");
    calls.forEach((span) =>
      additional.append(
        details(
          `${D.label(span.name)} · ${span.kind} · ${U.seconds(span.elapsed_seconds)}`,
          () => {
            const body = el("div");
            body.append(
              json("입력", span.input, true),
              json("반환 결과", span.output, true),
            );
            if (span.error) body.append(json("오류", span.error, true));
            return body;
          },
        ),
      ),
    );
    additional.append(json("이 노드의 판단·검증 기록", group.records));
    additional.append(json("노드 원본 JSON", node));
    panel.append(additional);
  }

  // 04. 저장된 설정만 표시합니다. 현재 PC의 .env는 읽지 않습니다.
  function renderSettings(report) {
    const panel = $("settings-content");
    panel.replaceChildren();
    const settings = card(
      "환경 변수에서 읽은 실행 설정",
      "보고서에 저장된 스냅샷입니다. 인증키 등 비밀 값은 수집 단계에서 제외됩니다.",
    );
    const saved = inspection.spans.filter((span) => span.input?.settings);
    if (!saved.length)
      settings.append(
        empty(
          "이 보고서에는 환경 설정 스냅샷이 없습니다. 현재 PC의 환경 변수로 대체하지 않습니다.",
        ),
      );
    for (const span of saved) {
      settings.append(el("p", "hint", span.name));
      settings.append(
        table(
          ["설정 항목", "저장된 값"],
          Object.entries(span.input.settings).map(([name, value]) => [
            name,
            U.text(value),
          ]),
        ),
      );
    }
    panel.append(settings);
    const execution = card("실행 한도·사용량");
    const budgetNames = {
      steps: "실행 단계",
      tool_calls: "도구 호출",
      agent_calls: "하위 Agent 호출",
      retries: "재시도",
      active_seconds: "실행 시간 (초)",
      final_model_calls: "마무리 모델 호출",
      final_active_seconds: "마무리 시간 (초)",
    };
    execution.append(
      table(
        ["항목", "사용량", "한도"],
        Object.entries(report.state.execution.budget || {}).map(
          ([name, value]) => [
            budgetNames[name] || name,
            U.format(value?.used),
            U.format(value?.limit),
          ],
        ),
      ),
    );
    execution.append(
      json("실행 예산 원본 · execution.budget", report.state.execution.budget),
    );
    execution.append(json("실행 메타데이터", report.state.execution));
    panel.append(execution);
    const generation = card(
      "모델 호출별 설정",
      "실제 HTTP 요청에 기록된 모델·생성 옵션·응답 형식입니다.",
    );
    let count = 0;
    inspection.models.forEach((span, index) => {
      const body = span.http_request?.body;
      if (!body || typeof body !== "object") return;
      const { messages, input, instructions, ...options } = body;
      generation.append(
        json(
          `${index + 1}. ${D.label(span.name)} · ${body.model || "모델명 미기록"}`,
          options,
        ),
      );
      count++;
    });
    if (!count)
      generation.append(empty("모델 요청의 설정 값이 기록되지 않았습니다."));
    panel.append(generation);
    panel.append(
      json("관측 범위와 제한", {
        scope: report.trace?.scope,
        limitations: report.trace?.limitations,
        coverage: report.trace?.coverage,
      }),
    );
    panel.append(el("p", "hint", "불러온 파일 · " + reports[current].name));
    panel.append(json("보고서 전체 원본 JSON", report));
  }

  // 05. 초기 State를 기준으로 이전 대화와 실행 시작 질문을 구분합니다.
  function renderConversation(report) {
    const panel = $("conversation-content");
    panel.replaceChildren();
    const conversation = D.conversation(report, inspection);
    if (!conversation.known) {
      panel.append(
        el(
          "p",
          "notice",
          "시작 시점의 State가 없어 이전 대화의 범위를 구분할 수 없습니다. 아래에는 저장된 메시지 전체를 표시합니다.",
        ),
      );
    }
    const messages = conversation.known
      ? conversation.previous
      : conversation.stored;
    if (!messages.length) panel.append(empty("기록된 이전 대화가 없습니다."));
    messages.forEach((message, index) => {
      const role = D.role(message);
      const block = card(
        `${String(index + 1).padStart(2, "0")} · ${D.roles[role] || role}`,
        null,
        "conversation-message",
      );
      block.append(el("div", "message-text", U.text(message.content)));
      block.append(json("메시지 원본", message));
      panel.append(block);
    });
    if (conversation.context?.length)
      panel.append(
        json("시작 시점의 시스템·도구 메시지", conversation.context),
      );
    panel.append(
      json("보고서 저장 시점의 메시지 전체 · messages", report.state.messages),
    );
  }

  function render() {
    renderSidebar();
    const report = currentReport();
    $("welcome").hidden = !!report;
    $("report-content").hidden = !report;
    $("download").disabled = !report;
    if (!report) return;
    inspection = D.inspect(report);
    searchIndex = new Map(
      inspection.groups.map((group) => [
        group.node.id,
        JSON.stringify(group).toLocaleLowerCase(),
      ]),
    );
    renderSummary(report);
    renderOverview(report);
    renderFlow(report);
    renderNodeList();
    renderSettings(report);
    renderConversation(report);
    showSection(section);
  }

  // 이벤트 연결. 영역을 추가할 때는 render 함수와 HTML도 함께 수정합니다.
  for (const control of $("sections").querySelectorAll("button")) {
    control.addEventListener("click", () =>
      showSection(control.dataset.section),
    );
  }
  $("node-search").addEventListener("input", () => {
    if (inspection) renderNodeList();
  });
  $("errors-only").addEventListener("change", () => {
    if (inspection) renderNodeList();
  });
  $("download").addEventListener("click", () => {
    const report = currentReport();
    if (!report) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
    );
    const link = el("a");
    link.href = url;
    link.download = (report.scenario || "agent") + "-report.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("files").addEventListener("change", async (event) => {
    const documents = [];
    const errors = [];
    for (const file of event.target.files) {
      try {
        if (file.size > 200 * 1024 * 1024)
          throw new Error("200MB 이하 파일을 선택해 주세요.");
        documents.push({
          name: file.name,
          value: JSON.parse((await file.text()).replace(/^\uFEFF/, "")),
        });
      } catch (error) {
        errors.push(file.name + ": " + error.message);
      }
    }
    const result = ingest(documents);
    errors.push(...result.errors);
    $("load-error").textContent = errors.join("\n");
    $("load-error").hidden = !errors.length;
    if (result.added) {
      selectedNode = null;
      render();
      U.toast(`${result.added}개 보고서를 불러왔습니다.`);
    }
    event.target.value = "";
  });
  try {
    const embedded = JSON.parse(
      $("report-data").textContent.replace("/*__REPORT_DATA__*/", ""),
    );
    const result = ingest(embedded);
    current = 0;
    $("load-error").textContent = result.errors.join("\n");
    $("load-error").hidden = !result.errors.length;
    render();
  } catch (error) {
    $("load-error").textContent =
      "보고서를 표시하지 못했습니다: " + error.message;
    $("load-error").hidden = false;
  }
})();
