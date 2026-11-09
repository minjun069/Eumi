/* 실행: node --test tests/test_report_viewer_data.cjs */
const { test } = require("node:test");
const assert = require("node:assert/strict");
require("../report_viewer/data.js");
const D = globalThis.ReportData;

function report(spans = []) {
  return {
    state: { results: [], messages: [], execution: { event: "user_request" } },
    trace: { spans },
  };
}

test("하위 모델 사용량을 상위 노드에 중복 합산하지 않고 실패 호출도 보존한다", () => {
  const value = report([
    { id: "a", kind: "agent", name: "root", sequence: 1 },
    { id: "n1", parent_id: "a", kind: "node", name: "act", sequence: 2 },
    {
      id: "m1",
      parent_id: "n1",
      kind: "model",
      sequence: 3,
      output: {
        sdk_response: {
          usage_metadata: { input_tokens: 10, output_tokens: 0 },
        },
      },
    },
    { id: "child", parent_id: "n1", kind: "agent", name: "child", sequence: 4 },
    { id: "n2", parent_id: "child", kind: "node", name: "act", sequence: 5 },
    {
      id: "m2",
      parent_id: "n2",
      kind: "model",
      sequence: 6,
      status: "error",
      error: { type: "ValidationError" },
      http_response: {
        body: { usage: { prompt_tokens: 30, completion_tokens: 4 } },
      },
    },
    { id: "m3", parent_id: "n2", kind: "model", sequence: 7 },
  ]);
  const before = JSON.stringify(value);
  const inspected = D.inspect(value);
  assert.equal(inspected.groups[0].tokens.input, 10);
  assert.equal(inspected.groups[0].tokens.outputRecorded, 1);
  assert.equal(inspected.groups[1].tokens.input, 30);
  assert.equal(inspected.groups[1].tokens.calls, 2);
  assert.equal(inspected.groups[1].tokens.inputRecorded, 1);
  assert.equal(inspected.groups[1].hasError, true);
  assert.equal(inspected.groups[1].calls[0].id, "m2");
  assert.equal(JSON.stringify(value), before);
});

test("시작 시점의 마지막 사용자 질문과 이전 대화를 분리하고 최종 답변을 섞지 않는다", () => {
  const messages = [
    { type: "system", content: "context" },
    { type: "human", content: "earlier" },
    { type: "ai", content: "earlier answer" },
    { type: "human", content: "current" },
  ];
  const value = report([
    {
      id: "a",
      kind: "agent",
      input: {
        initial_state: { messages, execution: { event: "user_request" } },
      },
    },
  ]);
  value.state.messages = [...messages, { type: "ai", content: "new answer" }];
  const conversation = D.conversation(value, D.inspect(value));
  assert.equal(conversation.current.content, "current");
  assert.deepEqual(
    conversation.previous.map((message) => message.content),
    ["earlier", "earlier answer"],
  );
  assert.equal(conversation.context.length, 1);
});

test("분석 이벤트의 과거 사용자 메시지를 이번 실행의 입력으로 표시하지 않는다", () => {
  const value = report([
    {
      id: "a",
      kind: "agent",
      input: {
        initial_state: {
          execution: { event: "analysis_pipeline" },
          messages: [{ type: "human", content: "past" }],
        },
      },
    },
  ]);
  const conversation = D.conversation(value, D.inspect(value));
  assert.equal(conversation.current, null);
  assert.equal(conversation.previous[0].content, "past");
});

test("trace 없는 보고서의 이전 대화 경계를 추정하지 않는다", () => {
  const value = report();
  value.state.messages = [{ type: "human", content: "stored" }];
  assert.equal(D.conversation(value, D.inspect(value)).known, false);
});

test("Responses API와 Chat Completions의 실제 요청을 원문 그대로 읽는다", () => {
  const response = {
    http_request: {
      body: {
        instructions: "system\nexact",
        input: [
          {
            role: "user",
            content: [{ type: "input_text", text: '{"goal": 1}' }],
          },
        ],
      },
    },
  };
  const messages = D.modelMessages(response).messages;
  assert.equal(messages[0].content, "system\nexact");
  assert.deepEqual(messages[1], response.http_request.body.input[0]);
  const chat = {
    http_request: { body: { messages: [{ role: "user", content: "exact" }] } },
  };
  assert.equal(D.modelMessages(chat).messages[0].content, "exact");
  assert.equal(
    D.modelMessages({
      input: { messages: [{ type: "system", content: "snapshot" }] },
    }).messages[0].content,
    "snapshot",
  );
});

test("과거 결과의 하위 Agent와 연속 노드를 나눠 표시한다", () => {
  const value = report();
  value.state.results = [
    {
      node: "act",
      output: {
        results: [
          {
            node: "act",
            output: { model_usage: { tokens: { input_tokens: 8 } } },
          },
        ],
      },
    },
    { node: "act", output: { model_usage: { tokens: { input_tokens: 2 } } } },
  ];
  const groups = D.inspect(value).groups;
  assert.equal(groups.length, 3);
  assert.equal(groups[1].tokens.input, 8);
  assert.equal(groups[2].tokens.input, 2);
  assert.equal(groups[0].node.elapsed_seconds, undefined);
});

test("누락된 사용량과 실제 0 토큰을 구별한다", () => {
  assert.equal(D.sumTokens([{}]).inputRecorded, 0);
  const zero = D.sumTokens([{ input: 0, output: 0 }]);
  assert.equal(zero.inputRecorded, 1);
  assert.equal(zero.output, 0);
});

test("모델 반환은 텍스트를 먼저 표시하고 SDK 메타데이터 원본은 유지한다", () => {
  const content = [
    { type: "reasoning", encrypted_content: "opaque" },
    { type: "text", text: '{"result":"exact"}' },
  ];
  const span = {
    output: { sdk_response: { content, usage_metadata: {} } },
    http_response: { body: { usage: { input_tokens: 12 } } },
  };
  assert.equal(D.modelOutput(span), '{"result":"exact"}');
  assert.equal(span.output.sdk_response.content[0].encrypted_content, "opaque");
  assert.equal(D.modelTokens(span).input, 12);
});
