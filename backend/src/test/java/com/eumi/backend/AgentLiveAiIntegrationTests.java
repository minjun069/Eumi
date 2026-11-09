package com.eumi.backend;

import java.time.Duration;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import com.eumi.backend.agent.*;
import com.eumi.backend.support.AgentHttpSupport;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import tools.jackson.databind.JsonNode;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** 사용자가 띄운 실제 FastAPI + PostgreSQL + 호스트 8080. 비밀값은 실행 환경에서만 받는다. */
@EnabledIfEnvironmentVariable(named = "EUMI_VERIFY_LIVE_AI", matches = "true")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.DEFINED_PORT, properties = {
        "server.port=8080", "eumi.ai.mode=http", "eumi.ai.base-url=http://127.0.0.1:8000",
        "eumi.ai.execution-limit=330s", "eumi.ai.grace-period=5s", "eumi.ai.unresponsive-after=40s", "eumi.ai.cancel-wait=3s"})
class AgentLiveAiIntegrationTests extends AgentHttpSupport {
    @MockitoSpyBean AgentClient client;
    @MockitoSpyBean AgentNotificationController notifications;
    private final ConcurrentHashMap<Long, Integer> delivered = new ConcurrentHashMap<>();
    private static final String PIPELINE = UUID.randomUUID().toString();
    @DynamicPropertySource static void tokens(DynamicPropertyRegistry registry) {
        registry.add("eumi.internal.pipeline-token", () -> PIPELINE);
        registry.add("eumi.internal.ai-token", () -> {
            String value = System.getenv("EUMI_AI_TOKEN");
            if (value == null || value.isBlank()) throw new IllegalStateException("Live AI token must be supplied through the environment.");
            return value;
        });
    }
    @BeforeEach void observeActualCallbacks() {
        delivered.clear();
        doAnswer(invocation -> {
            var input = (AgentDtos.Notification) invocation.getArgument(0);
            var response = (ResponseEntity<?>) invocation.callRealMethod();
            delivered.put(input.messageId(), response.getStatusCode().value());
            return response;
        }).when(notifications).notified(any());
    }

    @Test void committedQuestionReceivesActualAiAcceptanceAndTerminalNotification204() throws Exception {
        String request = "{\"conversationId\":null,\"question\":\"연결 검사입니다. 짧게 답해주세요.\",\"context\":{\"dongCode\":\"1168064000\",\"month\":\"2025-12\"}}";
        var accepted = browser.post("/agent/questions", request);
        assertThat(accepted.statusCode()).isEqualTo(202);
        var data = body(accepted); UUID id = conversation(data); long q = data.path("data").path("questionId").asLong();
        verify(client).start(id, q, new AgentDtos.ScreenContext("1168064000", "2025-12"));
        var terminal = waitForTerminal(id, Duration.ofSeconds(150));
        assertThat(terminal.path("questionId").asLong()).isEqualTo(q);
        // 가짜 LLM 키로 실행해도 AI가 실패 행을 커밋하고 INT-07을 보내는 실제 경로를 검사한다.
        assertThat(terminal.path("status").asText()).isIn("완료", "실패");
        awaitCallback(terminal.path("messageId").asLong());
    }

    @Test void cancellationUsesActualAiHttpAndProducesOneTerminal() throws Exception {
        var accepted = browser.post("/agent/questions", "{\"conversationId\":null,\"question\":\"해당 행정동의 위험 요인을 자세히 분석해 주세요.\",\"context\":{\"dongCode\":\"1168064000\",\"month\":\"2025-12\"}}");
        assertThat(accepted.statusCode()).isEqualTo(202);
        UUID id = conversation(body(accepted));
        assertThat(browser.post(cancelPath(id), null).statusCode()).isEqualTo(204);
        verify(client).cancel(id);
        var terminal = waitForTerminal(id, Duration.ofSeconds(8));
        assertThat(terminal.path("status").asText()).isIn("취소", "완료", "실패");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM ai_message WHERE conversation_id=? AND status IN ('완료','실패','취소')", Integer.class, id)).isEqualTo(1);
        awaitCallback(terminal.path("messageId").asLong());
    }

    private JsonNode waitForTerminal(UUID id, Duration timeout) throws Exception {
        long end = System.nanoTime() + timeout.toNanos();
        while (System.nanoTime() < end) {
            var response = browser.get(messagesPath(id));
            assertThat(response.statusCode()).isEqualTo(200);
            for (var row : body(response).path("data").path("messages")) {
                if (Set.of("완료", "실패", "취소").contains(row.path("status").asText())) return row;
            }
            Thread.sleep(200);
        }
        throw new AssertionError("Actual AI did not commit a terminal message within the test deadline.");
    }
    private void awaitCallback(long messageId) throws Exception {
        long end = System.nanoTime() + Duration.ofSeconds(5).toNanos();
        while (!delivered.containsKey(messageId) && System.nanoTime() < end) Thread.sleep(25);
        assertThat(delivered.get(messageId)).isEqualTo(204);
    }
}
