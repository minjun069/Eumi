package com.eumi.backend;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.time.LocalDate;
import java.util.Map;
import java.util.UUID;
import com.eumi.backend.support.ReportAiStub;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;

/** 실제 PostgreSQL + 실제 BE HTTP + INT-05 loopback 가짜 AI. 실제 AI 호출 없음. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ReportHttpIntegrationTests {
    private static final ReportAiStub AI = new ReportAiStub();
    private static final String AI_TOKEN = UUID.randomUUID().toString();
    private static final String PIPELINE_TOKEN = UUID.randomUUID().toString();
    private static final String PIPELINE = "/internal/analysis/pipeline-completions";
    private static final String COMPLETION = "/internal/analysis/insight-report-completions";
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired JsonMapper json;
    private final HttpClient http = HttpClient.newHttpClient();

    @DynamicPropertySource static void properties(DynamicPropertyRegistry p) {
        p.add("eumi.ai.mode", () -> "http"); p.add("eumi.ai.base-url", AI::baseUrl);
        p.add("eumi.ai.http-timeout", () -> "750ms");
        p.add("eumi.ai.execution-limit", () -> "60s"); p.add("eumi.ai.grace-period", () -> "2s");
        p.add("eumi.ai.unresponsive-after", () -> "5s"); p.add("eumi.ai.cancel-wait", () -> "2s");
        p.add("eumi.internal.ai-token", () -> AI_TOKEN); p.add("eumi.internal.pipeline-token", () -> PIPELINE_TOKEN);
    }
    @BeforeEach void reset() { AI.reset(); }
    @AfterAll static void stop() { AI.close(); }

    @Test void acceptedRequestContainsAllDistinctSortedTargetsAndSameResponseRequestId() throws Exception {
        var targets = jdbc.queryForList("SELECT DISTINCT adm_cd10 FROM public.region_result WHERE period_start=DATE '2025-12-01' ORDER BY adm_cd10", String.class);
        assertThat(targets).as("local analysis seed required").isNotEmpty();
        var response = send(PIPELINE, PIPELINE_TOKEN, "{\"month\":\"2025-12\",\"pipelineRunId\":\"synthetic-http\",\"reason\":\"RESULT_RELOAD\"}");
        assertThat(response.statusCode()).isEqualTo(202);
        var body = json.readTree(response.body());
        assertThat(body.path("data").path("targetCount").asInt()).isEqualTo(targets.size());
        assertThat(body.path("data").path("month").asText()).isEqualTo("2025-12");
        String requestId = response.headers().firstValue("X-Request-Id").orElseThrow();
        UUID.fromString(requestId);
        assertThat(body.path("meta").path("requestId").asText()).isEqualTo(requestId);
        assertThat(AI.requests).hasSize(1);
        var sent = AI.requests.getFirst(); var payload = json.readTree(sent.body());
        assertThat(sent.method()).isEqualTo("POST"); assertThat(sent.path()).isEqualTo("/internal/insight-reports/runs");
        assertThat(sent.authorization()).isNull();
        assertThat(payload.propertyNames()).containsExactlyInAnyOrder("requestId", "month", "dongCodes");
        assertThat(payload.path("requestId").asText()).isEqualTo(requestId);
        assertThat(payload.path("month").asText()).isEqualTo("2025-12");
        assertThat(payload.path("dongCodes")).isEqualTo(json.valueToTree(targets));
        assertThat(response.headers().allValues("Set-Cookie")).isEmpty();
    }

    @ParameterizedTest @ValueSource(ints = {200,204,400,409,503})
    void non202Returns503WithoutRetry(int status) throws Exception {
        AI.status = status;
        error(send(PIPELINE, PIPELINE_TOKEN, "{\"month\":\"2025-12\"}"), 503, "AI_UNAVAILABLE");
        assertThat(AI.requests).hasSize(1);
    }
    @Test void timeoutReturns503WithoutRetry() throws Exception {
        AI.delayMillis = 2000;
        long start = System.nanoTime();
        error(send(PIPELINE, PIPELINE_TOKEN, "{\"month\":\"2025-12\"}"), 503, "AI_UNAVAILABLE");
        assertThat(Duration.ofNanos(System.nanoTime() - start)).isLessThan(Duration.ofSeconds(2));
        assertThat(AI.requests).hasSize(1);
    }
    @Test void securityValidationAndMissingMonthNeverReachAi() throws Exception {
        error(send(PIPELINE, null, "{}"), 401, "UNAUTHENTICATED");
        error(send(PIPELINE, UUID.randomUUID().toString(), "{}"), 401, "UNAUTHENTICATED");
        error(send(PIPELINE, AI_TOKEN, "{}"), 403, "FORBIDDEN");
        error(send(PIPELINE, PIPELINE_TOKEN, "{\"month\":123}"), 400, "INVALID_JSON");
        error(send(PIPELINE, PIPELINE_TOKEN, "{\"month\":\"2025-12\",\"extra\":true}"), 400, "INVALID_JSON");
        error(send(PIPELINE, PIPELINE_TOKEN, "{\"month\":\"2025-13\"}"), 400, "VALIDATION_ERROR");
        var empty = LocalDate.of(1001, 1, 1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM public.region_result WHERE period_start=?", Long.class, empty)).isZero();
        error(send(PIPELINE, PIPELINE_TOKEN, "{\"month\":\"1001-01\"}"), 404, "NOT_FOUND");
        assertThat(AI.requests).isEmpty();
    }
    @Test void completionIsLogOnlyRepeatableAndCallerRestricted() throws Exception {
        String body = json.writeValueAsString(Map.of("requestId", "local-1", "month", "2025-12", "savedCount", 0, "failedDongCodes", java.util.List.of("1168066000")));
        long before = jdbc.queryForObject("SELECT count(*) FROM public.region_insight_report", Long.class);
        for (int i=0; i<2; i++) {
            var response = send(COMPLETION, AI_TOKEN, body);
            assertThat(response.statusCode()).isEqualTo(204); assertThat(response.body()).isEmpty();
            assertThat(response.headers().allValues("Set-Cookie")).isEmpty();
        }
        error(send(COMPLETION, null, body), 401, "UNAUTHENTICATED");
        error(send(COMPLETION, PIPELINE_TOKEN, body), 403, "FORBIDDEN");
        error(send(COMPLETION, AI_TOKEN, body.replace("\"local-1\"", "123")), 400, "INVALID_JSON");
        error(send(COMPLETION, AI_TOKEN, body.substring(0, body.length()-1) + ",\"extra\":1}"), 400, "INVALID_JSON");
        error(send(COMPLETION, AI_TOKEN, body.replace("\"savedCount\":0", "\"savedCount\":-1")), 400, "VALIDATION_ERROR");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM public.region_insight_report", Long.class)).isEqualTo(before);
        assertThat(AI.requests).isEmpty();
    }
    private HttpResponse<String> send(String path, String token, String body) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api" + path))
                .timeout(Duration.ofSeconds(5)).header("Content-Type", "application/json");
        if (token != null) request.header("Authorization", "Bearer " + token);
        return http.send(request.POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
    }
    private void error(HttpResponse<String> response, int status, String code) {
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(json.readTree(response.body()).path("error").path("code").asText()).isEqualTo(code);
    }
}
