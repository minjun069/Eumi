package com.eumi.backend;

import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
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
import static org.assertj.core.api.Assertions.assertThat;

/** 실제 PostgreSQL·A1 로그인·HTTP를 사용하며 공용 지역 기준 데이터는 읽기만 한다. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ReferenceDataIntegrationTests {
    private static final List<String> PATHS = List.of("/regions/sidos", "/regions/sidos/11/sigungus",
            "/regions/sigungus/11680/dongs", "/organizations/me/members");
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired PasswordEncoder passwords;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired JsonMapper json;
    private final List<Long> organizationIds = new ArrayList<>();
    private final List<Long> memberIds = new ArrayList<>();
    private final String fixtureName = "Reference synthetic " + UUID.randomUUID();
    private long orgId;
    private long otherOrgId;
    private long callerId;
    private long colleagueId;
    private long foreignId;
    private String email;
    private String password;
    private Browser browser;

    @BeforeEach
    void createSyntheticMembersAndSignIn() throws Exception {
        orgId = organization("11680");
        otherOrgId = organization("51110");
        email = "reference-" + UUID.randomUUID() + "@eumi.test";
        password = UUID.randomUUID() + "Aa1!";
        String hash = passwords.encode(password);
        callerId = member(orgId, email, "Z Reference caller", null, hash);
        colleagueId = member(orgId, "colleague-" + email, "A Reference colleague", "담당", hash);
        jdbc.update("UPDATE member SET temp_password_expires_at = now() + interval '1 hour' WHERE member_id = ?", colleagueId);
        long withdrawnId = member(orgId, "withdrawn-" + email, "B Reference withdrawn", null, hash);
        jdbc.update("UPDATE member SET withdrawn_at = now() WHERE member_id = ?", withdrawnId);
        foreignId = member(otherOrgId, "foreign-" + email, "Foreign reference", null, hash);
        browser = signIn();
    }

    private long organization(String sigungu) {
        long id = jdbc.queryForObject("INSERT INTO organization(org_name, jurisdiction_sigungu_code, official_domain) "
                + "VALUES (?, ?, 'eumi.test') RETURNING org_id", Long.class, fixtureName, sigungu);
        organizationIds.add(id);
        return id;
    }

    private long member(long organizationId, String address, String name, String title, String hash) {
        long id = jdbc.queryForObject("INSERT INTO member(org_id, email_normalized, name, title, password_hash) "
                + "VALUES (?, ?, ?, ?, ?) RETURNING member_id", Long.class, organizationId, address, name, title, hash);
        memberIds.add(id);
        return id;
    }

    private Browser signIn() throws Exception {
        var result = new Browser();
        assertThat(result.post("/auth/login", json.writeValueAsString(Map.of("email", email, "password", password)))
                .statusCode()).isEqualTo(200);
        return result;
    }

    @AfterEach
    void cleanupOnlySyntheticRowsAndSessions() {
        for (long id : memberIds) {
            sessions.findByPrincipalName(Long.toString(id)).keySet().forEach(sessions::deleteById);
            jdbc.update("DELETE FROM member WHERE member_id = ? AND org_id IN (?, ?)", id, orgId, otherOrgId);
        }
        for (long id : organizationIds) {
            jdbc.update("DELETE FROM organization WHERE org_id = ? AND org_name = ?", id, fixtureName);
        }
    }

    @Test
    void regionHierarchyMatchesActualViewsAndCodeOrder() throws Exception {
        var expectedSidos = jdbc.query("SELECT sido_code, sido_name FROM v_sido ORDER BY sido_code",
                (rs, row) -> Map.of("sidoCode", rs.getString(1), "sidoName", rs.getString(2)));
        assertThat(expectedSidos).as("dim_region의 기존 기준 데이터가 필요하다").isNotEmpty();
        assertThat(success(browser.get("/regions/sidos"))).isEqualTo(json.valueToTree(expectedSidos));
        for (var sido : expectedSidos) {
            String code = sido.get("sidoCode");
            var expectedSigungus = jdbc.query("SELECT sigungu_code, sigungu_name FROM v_sigungu WHERE sido_code = ? ORDER BY sigungu_code",
                    (rs, row) -> Map.of("sigunguCode", rs.getString(1), "sigunguName", rs.getString(2)), code);
            assertThat(success(browser.get("/regions/sidos/" + code + "/sigungus")))
                    .isEqualTo(json.valueToTree(expectedSigungus));
            for (var sigungu : expectedSigungus) {
                String sigunguCode = sigungu.get("sigunguCode");
                var expectedDongs = jdbc.query("SELECT adm_cd10, adm_nm FROM dim_region WHERE left(adm_cd10, 5) = ? ORDER BY adm_cd10",
                        (rs, row) -> Map.of("dongCode", rs.getString(1), "dongName", rs.getString(2)), sigunguCode);
                assertThat(success(browser.get("/regions/sigungus/" + sigunguCode + "/dongs")))
                        .isEqualTo(json.valueToTree(expectedDongs));
            }
        }
    }

    @Test
    void memberOptionsExcludeOtherOrganizationsAndWithdrawnMembersAndKeepNullTitle() throws Exception {
        var data = success(browser.get("/organizations/me/members?orgId=" + otherOrgId + "&memberId=" + foreignId));
        assertThat(data.size()).isEqualTo(2);
        assertThat(data.get(0).path("memberId").asLong()).isEqualTo(colleagueId);
        assertThat(data.get(1).path("memberId").asLong()).isEqualTo(callerId);
        assertThat(data.get(0).path("name").asText()).isEqualTo("A Reference colleague");
        assertThat(data.get(0).path("title").asText()).isEqualTo("담당");
        assertThat(data.get(1).has("title") && data.get(1).path("title").isNull()).isTrue();
        for (var row : data) assertThat(row.size()).isEqualTo(3);
    }

    @Test
    void memberScopeUsesLatestDatabaseOrganization() throws Exception {
        jdbc.update("UPDATE member SET org_id = ? WHERE member_id = ?", otherOrgId, callerId);
        var data = success(browser.get("/organizations/me/members"));
        assertThat(data.size()).isEqualTo(2);
        assertThat(data.get(0).path("memberId").asLong()).isEqualTo(foreignId);
        assertThat(data.get(1).path("memberId").asLong()).isEqualTo(callerId);
    }

    @ParameterizedTest
    @ValueSource(strings = {"/regions/sidos", "/regions/sidos/11/sigungus", "/regions/sigungus/11680/dongs", "/organizations/me/members"})
    void unauthenticatedRequestsAre401(String path) throws Exception {
        error(new Browser().get(path), 401, "UNAUTHENTICATED");
    }

    @ParameterizedTest
    @ValueSource(strings = {"/regions/sidos", "/regions/sidos/11/sigungus", "/regions/sigungus/11680/dongs", "/organizations/me/members"})
    void temporaryPasswordSessionIs403(String path) throws Exception {
        jdbc.update("UPDATE member SET temp_password_expires_at = now() + interval '1 hour' WHERE member_id = ?", callerId);
        browser = signIn();
        error(browser.get(path), 403, "PASSWORD_CHANGE_REQUIRED");
    }

    @Test
    void withdrawnCallerCannotContinueUsingReferenceApis() throws Exception {
        jdbc.update("UPDATE member SET withdrawn_at = now() WHERE member_id = ?", callerId);
        for (String path : PATHS) error(browser.get(path), 401, "UNAUTHENTICATED");
    }

    @ParameterizedTest
    @ValueSource(strings = {"/regions/sidos/1/sigungus", "/regions/sidos/111/sigungus", "/regions/sidos/ab/sigungus",
            "/regions/sigungus/1168/dongs", "/regions/sigungus/116800/dongs", "/regions/sigungus/11abc/dongs"})
    void malformedCodesAre400(String path) throws Exception {
        error(browser.get(path), 400, "VALIDATION_ERROR");
    }

    @Test
    void wellFormedButMissingParentsAre404() throws Exception {
        error(browser.get("/regions/sidos/99/sigungus"), 404, "NOT_FOUND");
        error(browser.get("/regions/sigungus/99999/dongs"), 404, "NOT_FOUND");
    }

    private JsonNode success(HttpResponse<String> response) {
        assertThat(response.statusCode()).isEqualTo(200);
        var body = responseBody(response);
        assertThat(body.path("success").asBoolean()).isTrue();
        assertThat(body.path("data").isArray()).isTrue();
        return body.path("data");
    }

    private void error(HttpResponse<String> response, int status, String code) {
        assertThat(response.statusCode()).isEqualTo(status);
        var body = responseBody(response);
        assertThat(body.path("success").asBoolean()).isFalse();
        assertThat(body.path("error").path("code").asText()).isEqualTo(code);
    }

    private JsonNode responseBody(HttpResponse<String> response) {
        assertThat(response.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");
        var body = json.readTree(response.body());
        String requestId = response.headers().firstValue("X-Request-Id").orElseThrow();
        UUID.fromString(requestId);
        assertThat(body.path("meta").path("requestId").asText()).isEqualTo(requestId);
        return body;
    }

    private class Browser {
        private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        private final HttpClient client = HttpClient.newBuilder().cookieHandler(cookies).connectTimeout(Duration.ofSeconds(3)).build();

        HttpResponse<String> get(String path) throws Exception {
            return client.send(request(path).GET().build(), HttpResponse.BodyHandlers.ofString());
        }

        HttpResponse<String> post(String path, String body) throws Exception {
            assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
            String token = cookies.getCookieStore().getCookies().stream().filter(c -> c.getName().equals("XSRF-TOKEN"))
                    .findFirst().orElseThrow().getValue();
            return client.send(request(path).header("X-XSRF-TOKEN", token).header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
        }

        private HttpRequest.Builder request(String path) {
            return HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api" + path)).timeout(Duration.ofSeconds(5));
        }
    }
}
