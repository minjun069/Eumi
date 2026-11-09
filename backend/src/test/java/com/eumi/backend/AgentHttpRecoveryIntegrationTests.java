package com.eumi.backend;

import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import com.eumi.backend.support.AgentHttpSupport;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.*;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import static org.assertj.core.api.Assertions.*;

/** 실제 PostgreSQL/BE/AI HTTP 클라이언트. AI의 행 미저장/접수 실패는 로컬 HTTP 대역으로 만든다. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "eumi.ai.mode=http", "eumi.ai.execution-limit=10s", "eumi.ai.grace-period=2s",
        "eumi.ai.unresponsive-after=100ms", "eumi.ai.cancel-wait=150ms"})
class AgentHttpRecoveryIntegrationTests extends AgentHttpSupport {
    private static final String AI = UUID.randomUUID().toString(), PIPELINE = UUID.randomUUID().toString();
    private static final List<Request> REQUESTS = new CopyOnWriteArrayList<>();
    private static final AtomicInteger START_STATUS = new AtomicInteger(202);
    private static final HttpServer STUB = stub();
    private record Request(String path, String body) { }
    private static HttpServer stub() {
        try {
            var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext("/internal/agent/runs", exchange -> {
                REQUESTS.add(new Request(exchange.getRequestURI().getPath(), new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8)));
                exchange.sendResponseHeaders(exchange.getRequestURI().getPath().endsWith("/cancel") ? 202 : START_STATUS.get(), -1);
                exchange.close();
            });
            server.start(); return server;
        } catch (java.io.IOException ex) { throw new ExceptionInInitializerError(ex); }
    }
    @DynamicPropertySource static void settings(DynamicPropertyRegistry registry) {
        registry.add("eumi.ai.base-url", () -> "http://127.0.0.1:" + STUB.getAddress().getPort());
        registry.add("eumi.internal.ai-token", () -> AI); registry.add("eumi.internal.pipeline-token", () -> PIPELINE);
    }
    @BeforeEach void resetHttp() { REQUESTS.clear(); START_STATUS.set(202); }
    @AfterAll static void closeHttp() { STUB.stop(0); }

    @Test void quietAiReceivesOneRetryWithIdenticalContextAndNoPrematureFailure() throws Exception {
        String request = "{\"conversationId\":null,\"question\":\"Synthetic context question\",\"context\":{\"dongCode\":\"1168064000\",\"month\":\"2025-12\"}}";
        var accepted = browser.post("/agent/questions", request);
        assertThat(accepted.statusCode()).isEqualTo(202);
        var created = body(accepted); UUID id = conversation(created);
        long q = created.path("data").path("questionId").asLong();
        assertThat(jdbc.queryForObject("SELECT content FROM ai_message WHERE message_id=?", String.class, q)).isEqualTo("Synthetic context question");
        jdbc.update("UPDATE ai_message SET created_at=now()-interval '1 second' WHERE message_id=?", q);
        for (int i = 0; i < 5; i++) assertThat(browser.get(messagesPath(id)).statusCode()).isEqualTo(200);
        var starts = REQUESTS.stream().filter(r -> r.path().equals("/internal/agent/runs")).toList();
        assertThat(starts).hasSize(2);
        assertThat(starts.get(0).body()).isEqualTo(starts.get(1).body());
        var sent = json.readTree(starts.getFirst().body());
        assertThat(sent.path("messageId").asLong()).isEqualTo(q);
        assertThat(sent.has("questionId")).isFalse();
        assertThat(sent.path("context").path("month").asText()).isEqualTo("2025-12");
        assertThat(aiRows(id)).isZero();
    }

    @Test void rejectedInitialAndRetryAdmissionWaitUntilAbsoluteDeadline() throws Exception {
        START_STATUS.set(503);
        var created = body(browser.post("/agent/questions", question(null, "Synthetic unavailable AI")));
        UUID id = conversation(created); long q = created.path("data").path("questionId").asLong();
        assertThat(aiRows(id)).isZero();
        jdbc.update("UPDATE ai_message SET created_at=now()-interval '1 second' WHERE message_id=?", q);
        for (int i = 0; i < 3; i++) browser.get(messagesPath(id));
        assertThat(REQUESTS).hasSize(2);
        assertThat(aiRows(id)).isZero();
        jdbc.update("UPDATE ai_message SET created_at=now()-interval '20 seconds' WHERE message_id=?", q);
        assertThat(awaitEnd(id).path("status").asText()).isEqualTo("실패");
        assertThat(REQUESTS).hasSize(2);
    }

    @Test void notificationRequiresAiTokenAndAnAiRowInTheGivenConversation() throws Exception {
        UUID id = pendingConversation(0); long q = pendingQuestion(id);
        long m = jdbc.queryForObject("INSERT INTO ai_message(conversation_id,question_id,role,status,content) VALUES (?,?,'AI','진행','Synthetic progress') RETURNING message_id", Long.class, id, q);
        String valid = "{\"conversationId\":\"" + id + "\",\"messageId\":" + m + "}";
        assertThat(notify(null, valid).statusCode()).isEqualTo(401);
        assertThat(notify(PIPELINE, valid).statusCode()).isEqualTo(403);
        assertThat(notify(AI, valid.replace(Long.toString(m), Long.toString(q))).statusCode()).isEqualTo(404);
        assertThat(notify(AI, valid.replace(id.toString(), UUID.randomUUID().toString())).statusCode()).isEqualTo(404);
        for (int i = 0; i < 2; i++) {
            var response = notify(AI, valid);
            assertThat(response.statusCode()).isEqualTo(204); assertThat(response.body()).isEmpty();
            assertThat(response.headers().allValues("Set-Cookie")).isEmpty();
        }
        assertThat(aiRows(id)).isEqualTo(1);
    }

    @Test void httpCancelAcknowledgementFallsBackAfterWaitingForMissingTerminal() throws Exception {
        var accepted = browser.post("/agent/questions", question(null, "Synthetic cancel"));
        UUID id = conversation(body(accepted));
        assertThat(browser.post(cancelPath(id), null).statusCode()).isEqualTo(204);
        assertThat(awaitEnd(id).path("status").asText()).isEqualTo("취소");
        assertThat(REQUESTS.stream().filter(r -> r.path().endsWith("/cancel")).count()).isEqualTo(1);
    }

    private long aiRows(UUID id) { return jdbc.queryForObject("SELECT count(*) FROM ai_message WHERE conversation_id=? AND role='AI'", Long.class, id); }
    private HttpResponse<String> notify(String token, String body) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/internal/agent/notifications"))
                .timeout(Duration.ofSeconds(3)).header("Content-Type", "application/json");
        if (token != null) request.header("Authorization", "Bearer " + token);
        return HttpClient.newHttpClient().send(request.POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
    }
}
