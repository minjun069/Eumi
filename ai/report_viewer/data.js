/* 저장된 보고서를 화면용으로 읽는 함수들. 원본 State와 trace는 수정하지 않습니다. */
"use strict";

globalThis.ReportData = (() => {
  const nodeNames = {
    interpret: "요청 해석",
    act: "작업 선택·실행",
    decide: "진행 판단",
    compose: "응답 작성",
    ask: "추가 질문",
    wait: "답변 대기",
    Interpretation: "요청 해석",
    Selection: "작업 선택",
    Verification: "결과 검증",
    Decision: "진행 판단",
    Composition: "응답 작성",
    Question: "질문 작성",
    ReportSelection: "보고서 뷰 선정",
    ReportText: "보고서 문장 작성",
  };
  const statuses = {
    completed: "완료",
    success: "성공",
    failed: "실패",
    error: "오류",
    partial: "부분 완료",
    waiting_input: "답변 대기",
    running: "실행 중",
    queued: "대기",
    cancelled: "취소",
    interrupted: "중단",
  };
  const roles = {
    human: "사용자",
    user: "사용자",
    ai: "Agent",
    assistant: "Agent",
    system: "시스템",
    developer: "개발자",
    tool: "도구",
  };
  const label = (name) => nodeNames[name] || name || "이름 미기록";
  const role = (message) => message.role || message.type;
  const isUser = (message) => ["human", "user"].includes(role(message));
  const numeric = (value) =>
    typeof value === "number" && Number.isFinite(value);

  function normalize(value) {
    const report = value?.state ? value : { state: value };
    if (!report.state?.execution || !Array.isArray(report.state.results)) {
      throw new Error("State가 포함된 report.json을 선택해 주세요.");
    }
    if (report.trace?.spans && !Array.isArray(report.trace.spans)) {
      throw new Error("trace.spans가 배열이 아닙니다.");
    }
    return report;
  }

  function flatten(records, depth = 0) {
    if (!Array.isArray(records) || depth > 30) return [];
    return records.flatMap((record) => [
      record,
      ...flatten(record?.output?.results, depth + 1),
    ]);
  }

  function ownerNode(span, index) {
    const visited = new Set();
    while (span && !visited.has(span.id)) {
      if (span.kind === "node") return span;
      visited.add(span.id);
      span = index.get(span.parent_id);
    }
    return null;
  }

  function ancestors(span, index) {
    const path = [];
    const visited = new Set([span.id]);
    let parent = index.get(span.parent_id);
    while (parent && !visited.has(parent.id)) {
      path.unshift(parent);
      visited.add(parent.id);
      parent = index.get(parent.parent_id);
    }
    return path;
  }

  function modelTokens(span) {
    const sdk = span.output?.sdk_response;
    const usage =
      [
        sdk?.usage_metadata,
        sdk?.response_metadata?.token_usage,
        span.http_response?.body?.usage,
      ].find(
        (value) =>
          value &&
          [
            value.input_tokens,
            value.prompt_tokens,
            value.output_tokens,
            value.completion_tokens,
          ].some(numeric),
      ) || {};
    return {
      input: usage.input_tokens ?? usage.prompt_tokens,
      output: usage.output_tokens ?? usage.completion_tokens,
    };
  }

  // 미기록을 0으로 취급하지 않습니다. 입력·출력별 기록된 호출 수도 보존합니다.
  function sumTokens(values) {
    const result = {
      input: 0,
      output: 0,
      inputRecorded: 0,
      outputRecorded: 0,
      calls: values.length,
    };
    for (const usage of values) {
      for (const key of ["input", "output"]) {
        if (numeric(usage[key])) {
          result[key] += usage[key];
          result[key + "Recorded"]++;
        }
      }
    }
    return result;
  }

  function legacyGroups(records, path = "최상위 실행", groups = []) {
    let group;
    for (const record of records || []) {
      if (!group || group.node.name !== record.node) {
        group = {
          node: {
            id: "legacy-" + groups.length,
            name: record.node,
            kind: "node",
          },
          order: groups.length + 1,
          path,
          calls: [],
          records: [],
          legacy: true,
        };
        groups.push(group);
      }
      group.records.push(record);
      if (record.output?.results) {
        legacyGroups(
          record.output.results,
          path + " › " + (record.action?.name || "하위 Agent"),
          groups,
        );
        group = null;
      }
    }
    return groups;
  }

  function inspect(report) {
    const spans = [...(report.trace?.spans || [])].sort(
      (a, b) => a.sequence - b.sequence,
    );
    const index = new Map(spans.map((span) => [span.id, span]));
    let groups = spans
      .filter((span) => span.kind === "node")
      .map((node, position) => ({
        node,
        order: position + 1,
        path:
          ancestors(node, index)
            .map((parent) => label(parent.name))
            .join(" › ") || "최상위 실행",
        calls: [],
        records: node.output?.node_update?.results || [],
        legacy: false,
      }));
    const byNode = new Map(groups.map((group) => [group.node.id, group]));
    for (const span of spans) {
      if (span.kind === "node") continue;
      byNode.get(ownerNode(span, index)?.id)?.calls.push(span);
    }
    if (!groups.length) groups = legacyGroups(report.state.results);
    for (const group of groups) {
      const usage = group.legacy
        ? group.records
            .filter((record) => record.output?.model_usage)
            .map((record) => ({
              input: record.output.model_usage.tokens?.input_tokens,
              output: record.output.model_usage.tokens?.output_tokens,
            }))
        : group.calls.filter((span) => span.kind === "model").map(modelTokens);
      group.tokens = sumTokens(usage);
      group.hasError =
        [group.node, ...group.calls].some(
          (span) => span.error || span.status === "error",
        ) || group.records.some((record) => record.outcome === "failure");
    }
    const models = spans.filter((span) => span.kind === "model");
    const initial =
      spans.find((span) => !span.parent_id && span.input?.initial_state)?.input
        .initial_state ||
      groups.find((group) => !group.legacy)?.node.input?.state;
    return { spans, index, groups, models, initial };
  }

  function conversation(report, inspection) {
    const initial = inspection.initial;
    if (!initial) return { known: false, stored: report.state.messages || [] };
    const messages = initial.messages || [];
    const event = initial.execution?.event || report.state.execution.event;
    const currentIndex =
      event === "analysis_pipeline" ? -1 : messages.findLastIndex(isUser);
    const previous =
      currentIndex < 0 ? messages : messages.slice(0, currentIndex);
    return {
      known: true,
      current: currentIndex < 0 ? null : messages[currentIndex],
      previous: previous.filter((message) =>
        ["human", "user", "ai", "assistant"].includes(role(message)),
      ),
      context: messages.filter(
        (message) =>
          !["human", "user", "ai", "assistant"].includes(role(message)),
      ),
      event,
    };
  }

  function modelMessages(span) {
    const body = span.http_request?.body;
    if (Array.isArray(body?.messages))
      return { source: "HTTP 요청 원문", messages: body.messages };
    // Responses API는 input과 instructions를 사용합니다.
    if (body && (body.input !== undefined || body.instructions !== undefined)) {
      const messages = [];
      if (body.instructions != null)
        messages.push({ role: "system", content: body.instructions });
      if (typeof body.input === "string")
        messages.push({ role: "user", content: body.input });
      else if (Array.isArray(body.input)) messages.push(...body.input);
      return { source: "HTTP 요청 원문", messages };
    }
    return {
      source: "모델 호출 직전 스냅샷",
      messages: span.input?.messages || [],
    };
  }

  // SDK의 암호화된 메타데이터 대신 실제 반환 텍스트를 먼저 읽습니다. 원본은 별도 보존합니다.
  function contentText(content) {
    if (!Array.isArray(content)) return content;
    const blocks = content.filter((block) =>
      ["text", "input_text", "output_text"].includes(block.type),
    );
    return blocks.length
      ? blocks.map((block) => block.text).join("\n")
      : content;
  }

  function modelOutput(span) {
    const sdkContent = span.output?.sdk_response?.content;
    if (sdkContent !== undefined) return contentText(sdkContent);
    const body = span.http_response?.body;
    const chat = body?.choices?.[0]?.message?.content;
    if (chat !== undefined) return contentText(chat);
    const messages = body?.output?.filter((item) => item.type === "message");
    if (messages?.length)
      return messages.map((message) => contentText(message.content)).join("\n");
    return body;
  }

  return {
    label,
    statuses,
    roles,
    role,
    numeric,
    normalize,
    flatten,
    inspect,
    conversation,
    modelTokens,
    sumTokens,
    modelMessages,
    contentText,
    modelOutput,
  };
})();
