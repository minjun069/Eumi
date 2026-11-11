package com.eumi.backend;

import java.net.URI;
import java.net.http.*;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;
import com.eumi.backend.support.AgentHttpSupport;
import com.eumi.backend.support.ReportAiStub;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import tools.jackson.databind.JsonNode;
import static org.assertj.core.api.Assertions.*;

/** 8080 + 실제 PostgreSQL. 검사용 미사용 월의 행만 생성/정리한다. 실제 AI 호출 없음. */
@EnabledIfEnvironmentVariable(named = "EUMI_REPORT_FIXTURES", matches = "true")
@ExtendWith(OutputCaptureExtension.class)
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.DEFINED_PORT, properties = "server.port=8080")
class ReportFakeIntegrationTests extends AgentHttpSupport {
    private static final ReportAiStub AI = new ReportAiStub();
    private static final String AI_TOKEN = UUID.randomUUID().toString(), PIPELINE_TOKEN = UUID.randomUUID().toString();
    private static final String QUICK = "Synthetic first line\nSynthetic second line";
    private static final OffsetDateTime GENERATED = OffsetDateTime.parse("2026-11-10T00:00:00Z");
    private JdbcTemplate pipeline, ai;
    private LocalDate month;
    private List<String> codes;
    private final Map<String, Timestamp> ownedRows = new HashMap<>();
    private final HttpClient http = HttpClient.newHttpClient();

    @DynamicPropertySource static void properties(DynamicPropertyRegistry p) {
        p.add("eumi.ai.mode", () -> "fake"); p.add("eumi.ai.base-url", AI::baseUrl);
        p.add("eumi.internal.ai-token", () -> AI_TOKEN); p.add("eumi.internal.pipeline-token", () -> PIPELINE_TOKEN);
    }
    @BeforeEach void createOwnedResults() throws Exception {
        AI.reset();
        try (var connection = jdbc.getDataSource().getConnection()) {
            String url = connection.getMetaData().getURL();
            pipeline = writer(url, "eumi_pipeline", "EUMI_TEST_PIPELINE_PASSWORD");
            ai = writer(url, "eumi_ai", "EUMI_TEST_AI_PASSWORD");
        }
        // 기존 월/결과를 덮어쓰지 않는다. 오래된 검사용 월이 비어 있는지 먼저 확인한다.
        do { month = LocalDate.of(ThreadLocalRandom.current().nextInt(1100, 1700), ThreadLocalRandom.current().nextInt(1, 13), 1); }
        while (jdbc.queryForObject("SELECT count(*) FROM public.region_result WHERE period_start=?", Long.class, month) != 0);
        codes = jdbc.queryForList("SELECT adm_cd10 FROM public.dim_region ORDER BY adm_cd10 LIMIT 3", String.class);
        assertThat(codes).hasSize(3);
        for (String code : codes) {
            Timestamp updated = pipeline.queryForObject("INSERT INTO public.region_result(period_start,adm_cd10,bg_score,bg_grade,bh_score,bh_grade,risk_grade) "
                    + "VALUES (?,?,12.34,2,56.78,4,4) RETURNING updated_at", Timestamp.class, month, code);
            ownedRows.put(code, updated);
        }
    }
    private JdbcTemplate writer(String url, String username, String env) {
        String secret = System.getenv(env);
        if (secret == null || secret.isBlank()) throw new IllegalStateException("Test DB credential environment is required: " + env);
        return new JdbcTemplate(new DriverManagerDataSource(url, username, secret));
    }
    @AfterEach void deleteOnlyOwnedResults() {
        if (pipeline != null) ownedRows.forEach((code, updated) ->
                pipeline.update("DELETE FROM public.region_result WHERE period_start=? AND adm_cd10=? AND updated_at=?", month, code, updated));
        ownedRows.clear();
    }
    @AfterAll static void stop() { AI.close(); }

    @Test void fakeAdmissionAiSavedSlotsAndDuplicateCompletionWorkThrough8080() throws Exception {
        assertThat(port).isEqualTo(8080);
        var admitted = internal("/pipeline-completions", PIPELINE_TOKEN, json.writeValueAsString(Map.of("month", ym(), "pipelineRunId", "synthetic-fake", "reason", "FULL")));
        assertThat(admitted.statusCode()).isEqualTo(202);
        var accepted = body(admitted);
        assertThat(accepted.path("data").path("targetCount").asInt()).isEqualTo(codes.size());
        assertThat(accepted.path("data").path("month").asText()).isEqualTo(ym());
        String id = admitted.headers().firstValue("X-Request-Id").orElseThrow();
        assertThat(accepted.path("meta").path("requestId").asText()).isEqualTo(id);
        assertThat(admitted.headers().allValues("Set-Cookie")).isEmpty();
        assertThat(reportCount()).isZero(); // fake는 보고서를 생성하거나 INT-05를 보내지 않는다.
        String code = codes.getFirst(); save(code, "EmbedDetailV03");
        String completion = json.writeValueAsString(Map.of("requestId", id, "month", ym(), "savedCount", 1, "failedDongCodes", List.of()));
        for (int i=0; i<2; i++) {
            var response = internal("/insight-report-completions", AI_TOKEN, completion);
            assertThat(response.statusCode()).isEqualTo(204); assertThat(response.body()).isEmpty();
        }
        assertThat(reportCount()).isEqualTo(1);
        var insight = data(browser.get(path(code, "insight")));
        assertThat(insight.path("insight").path("summary")).isEqualTo(json.valueToTree(List.of(QUICK)));
        var report = data(browser.get(path(code, "report"))).path("report");
        assertThat(report.propertyNames()).containsExactlyInAnyOrder("quickInsight", "graphs", "generatedAt");
        assertThat(report.path("quickInsight").asText()).isEqualTo(QUICK);
        assertThat(report.path("graphs")).isEqualTo(json.valueToTree(List.of(
                Map.of("sheet", "EmbedDetailV03", "description", "Synthetic graph 1"),
                Map.of("sheet", "EmbedDetailV01", "description", "Synthetic graph 2"),
                Map.of("sheet", "EmbedDetailV08", "description", "Synthetic graph 3"))));
        assertThat(Instant.parse(report.path("generatedAt").asText())).isEqualTo(GENERATED.toInstant());
        assertThat(AI.requests).isEmpty();
    }
    @Test void staleAndMissingReportsAreNullWhileScoresRemainAvailable() throws Exception {
        String code = codes.getFirst(); save(code, "EmbedDetailV03");
        Timestamp changed = pipeline.queryForObject("UPDATE public.region_result SET updated_at=updated_at+interval '1 second' "
                + "WHERE period_start=? AND adm_cd10=? AND updated_at=? RETURNING updated_at", Timestamp.class, month, code, ownedRows.get(code));
        ownedRows.put(code, changed);
        for (String dong : List.of(code, codes.get(1))) {
            var insight = data(browser.get(path(dong, "insight")));
            assertThat(insight.path("insight").isNull()).isTrue();
            assertThat(insight.path("riskGrade").asInt()).isEqualTo(4);
            assertThat(data(browser.get(path(dong, "report"))).path("report").isNull()).isTrue();
        }
    }
    @Test void unsupportedSheetSkipsOnlyThatGraphAndWritesWarning(CapturedOutput output) throws Exception {
        String code = codes.getFirst(); save(code, "EmbedDetailV09");
        var response = browser.get(path(code, "report"));
        var report = data(response).path("report");
        assertThat(report.propertyNames()).containsExactlyInAnyOrder("quickInsight", "graphs", "generatedAt");
        assertThat(report.path("quickInsight").asText()).isEqualTo(QUICK);
        assertThat(report.path("graphs")).isEqualTo(json.valueToTree(List.of(
                Map.of("sheet", "EmbedDetailV01", "description", "Synthetic graph 2"),
                Map.of("sheet", "EmbedDetailV08", "description", "Synthetic graph 3"))));
        assertThat(data(browser.get(path(code, "insight"))).path("insight").path("summary")).isEqualTo(json.valueToTree(List.of(QUICK)));
        assertThat(output.getAll().lines().filter(line -> line.contains("Saved report graph skipped")).toList())
                .singleElement().asString().contains("WARN", "Saved report graph skipped: unsupported sheet requestId="
                        + response.headers().firstValue("X-Request-Id").orElseThrow() + " month=" + ym() + " slot=1");
        assertThat(output.getAll()).doesNotContain(QUICK, "Synthetic graph 1", "Synthetic graph 2", "Synthetic graph 3",
                "EmbedDetailV09", "Saved report hidden");
    }
    @Test void partiallySavedSlotsKeepOrderAndNullDescriptionKey(CapturedOutput output) throws Exception {
        String code = codes.getFirst(); savePartial(code, QUICK);
        var report = data(browser.get(path(code, "report"))).path("report");
        assertThat(report.propertyNames()).containsExactlyInAnyOrder("quickInsight", "graphs", "generatedAt");
        assertThat(report.path("quickInsight").asText()).isEqualTo(QUICK);
        var graphs = report.path("graphs");
        assertThat(graphs.size()).isEqualTo(2);
        assertThat(graphs.get(0).path("sheet").asText()).isEqualTo("EmbedDetailV03");
        assertThat(graphs.get(0).path("description").asText()).isEqualTo("Synthetic graph 1");
        assertThat(graphs.get(1).path("sheet").asText()).isEqualTo("EmbedDetailV08");
        assertThat(graphs.get(1).propertyNames()).containsExactlyInAnyOrder("sheet", "description");
        assertThat(graphs.get(1).path("description").isNull()).isTrue();
        assertThat(Instant.parse(report.path("generatedAt").asText())).isEqualTo(GENERATED.toInstant());
        assertThat(output.getAll()).doesNotContain("Saved report graph skipped");
    }
    @Test void nullQuickInsightStaysNullInInsightAndReportResponses() throws Exception {
        String code = codes.getFirst(); savePartial(code, null);
        var insight = data(browser.get(path(code, "insight")));
        assertThat(insight.has("insight")).isTrue();
        assertThat(insight.path("insight").isNull()).isTrue();
        assertThat(insight.path("riskGrade").asInt()).isEqualTo(4);
        var report = data(browser.get(path(code, "report"))).path("report");
        assertThat(report.propertyNames()).containsExactlyInAnyOrder("quickInsight", "graphs", "generatedAt");
        assertThat(report.path("quickInsight").isNull()).isTrue();
        assertThat(report.path("graphs").size()).isEqualTo(2);
    }
    @Test void quickInsightOnlyReportHasEmptyGraphsThroughHttp() throws Exception {
        String code = codes.getFirst();
        ai.update("INSERT INTO public.region_insight_report(period_start,adm_cd10,quick_insight,result_updated_at,generated_at) "
                + "VALUES (?,?,?,?,?)", month, code, QUICK, ownedRows.get(code), GENERATED);
        var report = data(browser.get(path(code, "report"))).path("report");
        assertThat(report.propertyNames()).containsExactlyInAnyOrder("quickInsight", "graphs", "generatedAt");
        assertThat(report.path("quickInsight").asText()).isEqualTo(QUICK);
        assertThat(report.path("graphs")).isEqualTo(json.valueToTree(List.of()));
    }
    @Test void onlyUnsupportedSheetWithoutQuickInsightReturnsNullReport() throws Exception {
        String code = codes.getFirst();
        ai.update("INSERT INTO public.region_insight_report(period_start,adm_cd10,graph_2,result_updated_at,generated_at) "
                + "VALUES (?,?,?,?,?)", month, code, "EmbedDetailV09", ownedRows.get(code), GENERATED);
        assertThat(data(browser.get(path(code, "report"))).path("report").isNull()).isTrue();
    }
    @Test void databaseRejectsEmptyReportWithCheckViolation() {
        String code = codes.getFirst();
        assertThatThrownBy(() -> ai.update("INSERT INTO public.region_insight_report(period_start,adm_cd10,result_updated_at,generated_at) "
                + "VALUES (?,?,?,?)", month, code, ownedRows.get(code), GENERATED))
                .isInstanceOfSatisfying(DataIntegrityViolationException.class, ex -> assertThat(ex.getMostSpecificCause())
                        .isInstanceOfSatisfying(SQLException.class, sql -> assertThat(sql.getSQLState()).isEqualTo("23514")));
    }
    @Test void databaseRejectsDescriptionWithoutGraphWithCheckViolation() {
        String code = codes.getFirst();
        assertThatThrownBy(() -> ai.update("INSERT INTO public.region_insight_report(period_start,adm_cd10,quick_insight,desc_2,result_updated_at,generated_at) "
                + "VALUES (?,?,?,?,?,?)", month, code, QUICK, "Synthetic orphan description", ownedRows.get(code), GENERATED))
                .isInstanceOfSatisfying(DataIntegrityViolationException.class, ex -> assertThat(ex.getMostSpecificCause())
                        .isInstanceOfSatisfying(SQLException.class, sql -> assertThat(sql.getSQLState()).isEqualTo("23514")));
    }
    @Test void authRejectionsAndMissingResultsWorkWithRealDatabaseAndHttp() throws Exception {
        String path = path(codes.getFirst(), "report");
        error(new Browser().get(path), 401, "UNAUTHENTICATED");
        jdbc.update("UPDATE member SET temp_password_expires_at=now()+interval '1 hour' WHERE member_id=?", memberId);
        error(browser.get(path), 403, "PASSWORD_CHANGE_REQUIRED");
        jdbc.update("UPDATE member SET temp_password_expires_at=NULL WHERE member_id=?", memberId);
        for (String type : List.of("insight", "report")) {
            error(browser.get("/analysis/dongs/9999999999/" + type + "?month=" + ym()), 404, "NOT_FOUND");
            error(browser.get("/analysis/dongs/" + codes.getFirst() + "/" + type + "?month=1001-01"), 404, "NOT_FOUND");
        }
        error(internal("/pipeline-completions", AI_TOKEN, "{}"), 403, "FORBIDDEN");
        error(internal("/insight-report-completions", PIPELINE_TOKEN, "{}"), 403, "FORBIDDEN");
        assertThat(AI.requests).isEmpty();
    }
    private void save(String code, String firstSheet) {
        ai.update("INSERT INTO public.region_insight_report(period_start,adm_cd10,quick_insight,graph_1,desc_1,graph_2,desc_2,graph_3,desc_3,result_updated_at,generated_at) "
                + "VALUES (?,?,?,?,?,?,?,?,?,?,?)", month, code, QUICK, firstSheet, "Synthetic graph 1", "EmbedDetailV01", "Synthetic graph 2",
                "EmbedDetailV08", "Synthetic graph 3", ownedRows.get(code), GENERATED);
    }
    private void savePartial(String code, String quick) {
        ai.update("INSERT INTO public.region_insight_report(period_start,adm_cd10,quick_insight,graph_1,desc_1,graph_2,desc_2,graph_3,desc_3,result_updated_at,generated_at) "
                + "VALUES (?,?,?,?,?,?,?,?,?,?,?)", month, code, quick, "EmbedDetailV03", "Synthetic graph 1", null, null,
                "EmbedDetailV08", null, ownedRows.get(code), GENERATED);
    }
    private long reportCount() { return jdbc.queryForObject("SELECT count(*) FROM public.region_insight_report WHERE period_start=?", Long.class, month); }
    private String ym() { return month.toString().substring(0, 7); }
    private String path(String code, String type) { return "/analysis/dongs/" + code + "/" + type + "?month=" + ym(); }
    private JsonNode data(HttpResponse<String> response) { assertThat(response.statusCode()).isEqualTo(200); return body(response).path("data"); }
    private void error(HttpResponse<String> response, int status, String code) {
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(body(response).path("error").path("code").asText()).isEqualTo(code);
    }
    private HttpResponse<String> internal(String suffix, String token, String body) throws Exception {
        return http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/internal/analysis" + suffix))
                .timeout(Duration.ofSeconds(5)).header("Content-Type", "application/json").header("Authorization", "Bearer " + token)
                .POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
    }
}
