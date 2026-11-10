package com.eumi.backend;

import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.session.jdbc.JdbcIndexedSessionRepository;
import org.springframework.test.context.ActiveProfiles;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;

/** 실제 A1 인증·PostgreSQL·HTTP. 공용 분석·인사이트·보고서 데이터는 읽기만 한다. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class AnalysisIntegrationTests {
    private static final String INSIGHT = "/analysis/dongs/1168066000/insight?month=2025-12";
    private static final String REPORT = "/analysis/dongs/1168066000/report?month=2025-12";
    private static final List<String> PATHS = List.of("/analysis/sigungus/11680/months", INSIGHT, REPORT);
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired PasswordEncoder passwords;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired JsonMapper json;
    private long orgId;
    private long memberId;
    private String email;
    private String password;
    private final String fixtureName = "Analysis synthetic " + UUID.randomUUID();
    private Browser browser;

    @BeforeEach
    void createSyntheticMemberAndLogin() throws Exception {
        orgId = jdbc.queryForObject("INSERT INTO organization(org_name, jurisdiction_sigungu_code, official_domain) "
                + "VALUES (?, '11680', 'eumi.test') RETURNING org_id", Long.class, fixtureName);
        email = "analysis-" + UUID.randomUUID() + "@eumi.test";
        password = UUID.randomUUID() + "Aa1!";
        memberId = jdbc.queryForObject("INSERT INTO member(org_id, email_normalized, name, password_hash) "
                + "VALUES (?, ?, 'Analysis synthetic', ?) RETURNING member_id", Long.class, orgId, email, passwords.encode(password));
        browser = login();
    }

    private Browser login() throws Exception {
        var result = new Browser();
        assertThat(result.post("/auth/login", json.writeValueAsString(Map.of("email", email, "password", password))).statusCode()).isEqualTo(200);
        return result;
    }

    @AfterEach
    void cleanupOnlyOwnedFixtures() {
        if (memberId != 0) {
            sessions.findByPrincipalName(Long.toString(memberId)).keySet().forEach(sessions::deleteById);
            jdbc.update("DELETE FROM member WHERE member_id=? AND org_id=?", memberId, orgId);
        }
        if (orgId != 0) jdbc.update("DELETE FROM organization WHERE org_id=? AND org_name=?", orgId, fixtureName);
    }

    @Test
    void monthsAreDistinctSortedAndReadableOutsideOwnJurisdiction() throws Exception {
        for (String code : List.of("11680", "51110")) {
            var expected = jdbc.query("SELECT DISTINCT period_start FROM public.region_result "
                    + "WHERE left(adm_cd10,5)=? ORDER BY period_start",
                    (rs, row) -> rs.getObject(1, LocalDate.class).toString().substring(0, 7), code);
            assertThat(expected).as("region_result seed is required").isNotEmpty();
            var data = success(browser.get("/analysis/sigungus/" + code + "/months"));
            assertThat(data.size()).isEqualTo(1);
            assertThat(data.path("months")).isEqualTo(json.valueToTree(expected));
        }
        // 관할 밖의 읍면동 조회 역시 허용된다.
        var outside = jdbc.queryForObject("SELECT adm_cd10 FROM public.region_result WHERE left(adm_cd10,5)='51110' "
                + "AND period_start=DATE '2025-12-01' ORDER BY adm_cd10 LIMIT 1", String.class);
        success(browser.get("/analysis/dongs/" + outside + "/insight?month=2025-12"));
        success(browser.get("/analysis/dongs/" + outside + "/report?month=2025-12"));
    }

    @Test
    void insightMatchesPersistedScoresAndExplicitNullWhenGenerationIsPending() throws Exception {
        var expected = jdbc.queryForMap("SELECT dong_name,sigungu_name,bg_score,bg_grade,bh_score,bh_grade,risk_grade,quick_insight "
                + "FROM public.v_region_insight WHERE adm_cd10='1168066000' "
                + "AND period_start=DATE '2025-12-01'");
        var data = success(browser.get(INSIGHT));
        assertThat(data.size()).isEqualTo(9);
        assertThat(data.path("dongCode").asText()).isEqualTo("1168066000");
        assertThat(data.path("dongName").asText()).isEqualTo(expected.get("dong_name"));
        assertThat(data.path("sigunguCode").asText()).isEqualTo("11680");
        assertThat(data.path("sigunguName").asText()).isEqualTo(expected.get("sigungu_name"));
        assertThat(data.path("month").asText()).isEqualTo("2025-12");
        assertThat(data.path("background").path("score").decimalValue()).isEqualByComparingTo(expected.get("bg_score").toString());
        assertThat(data.path("behavior").path("score").decimalValue()).isEqualByComparingTo(expected.get("bh_score").toString());
        assertThat(data.path("background").path("stage").asInt()).isEqualTo(((Number) expected.get("bg_grade")).intValue());
        assertThat(data.path("behavior").path("stage").asInt()).isEqualTo(((Number) expected.get("bh_grade")).intValue());
        assertThat(data.path("riskGrade").asInt()).isEqualTo(((Number) expected.get("risk_grade")).intValue());
        assertThat(data.has("insight")).isTrue();
        if (expected.get("quick_insight") == null) assertThat(data.path("insight").isNull()).isTrue();
        else {
            assertThat(data.path("insight").path("summary")).isEqualTo(json.valueToTree(List.of(expected.get("quick_insight"))));
            Instant.parse(data.path("insight").path("generatedAt").asText());
        }
    }

    @Test
    void absentReportIsExplicitNullAndReadsDoNotGenerateData() throws Exception {
        long before = jdbc.queryForObject("SELECT count(*) FROM public.region_insight_report", Long.class);
        var data = success(browser.get(REPORT));
        assertThat(data.size()).isEqualTo(1);
        assertThat(data.has("report")).isTrue();
        boolean generated = Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM public.region_insight_report i "
                + "JOIN public.region_result r USING(adm_cd10,period_start) WHERE i.adm_cd10='1168066000' AND i.period_start=DATE '2025-12-01' "
                + "AND i.result_updated_at=r.updated_at AND i.graph_1 IN ('EmbedDetailV01','EmbedDetailV02','EmbedDetailV03','EmbedDetailV04','EmbedDetailV05','EmbedDetailV06','EmbedDetailV07','EmbedDetailV08') "
                + "AND i.graph_2 IN ('EmbedDetailV01','EmbedDetailV02','EmbedDetailV03','EmbedDetailV04','EmbedDetailV05','EmbedDetailV06','EmbedDetailV07','EmbedDetailV08') "
                + "AND i.graph_3 IN ('EmbedDetailV01','EmbedDetailV02','EmbedDetailV03','EmbedDetailV04','EmbedDetailV05','EmbedDetailV06','EmbedDetailV07','EmbedDetailV08'))", Boolean.class));
        if (!generated) assertThat(data.path("report").isNull()).isTrue();
        else Instant.parse(data.path("report").path("generatedAt").asText());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM public.region_insight_report", Long.class)).isEqualTo(before);
    }

    @Test
    void missingRegionOrResultIs404() throws Exception {
        error(browser.get("/analysis/sigungus/99999/months"), 404, "NOT_FOUND");
        error(browser.get("/analysis/dongs/9999999999/insight?month=2025-12"), 404, "NOT_FOUND");
        error(browser.get("/analysis/dongs/9999999999/report?month=2025-12"), 404, "NOT_FOUND");
        error(browser.get("/analysis/dongs/1168066000/insight?month=1900-01"), 404, "NOT_FOUND");
        error(browser.get("/analysis/dongs/1168066000/report?month=1900-01"), 404, "NOT_FOUND");
        error(browser.get("/analysis/dongs/1168066000/insight?month=0000-01"), 404, "NOT_FOUND");
        error(browser.get("/analysis/dongs/1168066000/report?month=0000-01"), 404, "NOT_FOUND");
    }

    @Test
    void unauthenticatedAndTemporarySessionsAreRejectedOnAllThreeEndpoints() throws Exception {
        for (String path : PATHS) error(new Browser().get(path), 401, "UNAUTHENTICATED");
        jdbc.update("UPDATE member SET temp_password_expires_at=now()+interval '1 hour' WHERE member_id=?", memberId);
        // 기존 정상 세션에도 최신 DB의 제한을 적용한다.
        for (String path : PATHS) error(browser.get(path), 403, "PASSWORD_CHANGE_REQUIRED");
        browser = login();
        for (String path : PATHS) error(browser.get(path), 403, "PASSWORD_CHANGE_REQUIRED");
    }

    @Test
    void withdrawnMemberCannotKeepReadingAnalysis() throws Exception {
        jdbc.update("UPDATE member SET withdrawn_at=now() WHERE member_id=?", memberId);
        for (String path : PATHS) error(browser.get(path), 401, "UNAUTHENTICATED");
    }

    @ParameterizedTest
    @ValueSource(strings = {"/analysis/sigungus/1168/months", "/analysis/sigungus/116800/months", "/analysis/sigungus/11abc/months",
            "/analysis/dongs/11680660/insight?month=2025-12", "/analysis/dongs/11680660/report?month=2025-12",
            "/analysis/dongs/abcdefghij/insight?month=2025-12", "/analysis/dongs/1168066000/insight",
            "/analysis/dongs/1168066000/report", "/analysis/dongs/1168066000/insight?month=2025-13",
            "/analysis/dongs/1168066000/report?month=2025-00", "/analysis/dongs/1168066000/insight?month=2025-1",
            "/analysis/dongs/1168066000/report?month=2025-12-01"})
    void malformedCodeOrMonthIs400(String path) throws Exception { error(browser.get(path), 400, "VALIDATION_ERROR"); }

    private JsonNode success(HttpResponse<String> response) {
        assertThat(response.statusCode()).isEqualTo(200);
        var body = body(response);
        assertThat(body.path("success").asBoolean()).isTrue();
        return body.path("data");
    }

    private void error(HttpResponse<String> response, int status, String code) {
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(body(response).path("error").path("code").asText()).isEqualTo(code);
    }

    private JsonNode body(HttpResponse<String> response) {
        assertThat(response.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");
        var body = json.readTree(response.body());
        String id = response.headers().firstValue("X-Request-Id").orElseThrow();
        UUID.fromString(id);
        assertThat(body.path("meta").path("requestId").asText()).isEqualTo(id);
        return body;
    }

    private class Browser {
        private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        private final HttpClient client = HttpClient.newBuilder().cookieHandler(cookies).connectTimeout(Duration.ofSeconds(3)).build();
        HttpResponse<String> get(String path) throws Exception {
            return client.send(request(path).GET().build(), HttpResponse.BodyHandlers.ofString());
        }
        HttpResponse<String> post(String path, String content) throws Exception {
            assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
            String token = cookies.getCookieStore().getCookies().stream().filter(c -> c.getName().equals("XSRF-TOKEN"))
                    .findFirst().orElseThrow().getValue();
            return client.send(request(path).header("Content-Type", "application/json").header("X-XSRF-TOKEN", token)
                    .POST(HttpRequest.BodyPublishers.ofString(content)).build(), HttpResponse.BodyHandlers.ofString());
        }
        private HttpRequest.Builder request(String path) {
            return HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api" + path)).timeout(Duration.ofSeconds(5));
        }
    }
}
