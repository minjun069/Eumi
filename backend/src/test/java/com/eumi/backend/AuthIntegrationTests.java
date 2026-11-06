package com.eumi.backend;

import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
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

/** 실제 PostgreSQL·HTTP·PBKDF2·JDBC 세션 사용. 인증 대체 컨트롤러를 등록하지 않는다. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class AuthIntegrationTests {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired PasswordEncoder passwords;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired JsonMapper mapper;
    private CookieManager cookies;
    private HttpClient client;
    private long orgId;
    private long memberId;
    private String email;
    private String password;
    private final List<String> createdSessionIds = new ArrayList<>();

    @BeforeEach
    void prepareSyntheticMember() {
        cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        client = HttpClient.newBuilder().cookieHandler(cookies).connectTimeout(Duration.ofSeconds(5)).build();
        email = "a1-" + UUID.randomUUID() + "@eumi.test";
        password = UUID.randomUUID() + "Aa1!";
        orgId = jdbc.queryForObject("""
                INSERT INTO organization(org_name, jurisdiction_sigungu_code, official_domain)
                VALUES ('A1 synthetic integration', '11680', 'eumi.test') RETURNING org_id
                """, Long.class);
        memberId = jdbc.queryForObject("""
                INSERT INTO member(org_id, email_normalized, name, title, password_hash)
                VALUES (?, ?, '검사용 회원', NULL, ?) RETURNING member_id
                """, Long.class, orgId, email, passwords.encode(password));
    }

    @AfterEach
    void cleanOnlyThisTestsData() {
        createdSessionIds.forEach(sessions::deleteById);
        sessions.findByPrincipalName(Long.toString(memberId)).keySet().forEach(sessions::deleteById);
        jdbc.update("DELETE FROM member WHERE member_id = ? AND email_normalized = ?", memberId, email);
        jdbc.update("DELETE FROM organization WHERE org_id = ? AND org_name = 'A1 synthetic integration'", orgId);
    }

    @Test
    void loginLatestProfileLogoutAndUnauthorizedThroughActualHttp() throws Exception {
        assertThat(get("/auth/me").statusCode()).isEqualTo(401);
        var login = login("  " + email.toUpperCase(java.util.Locale.ROOT) + "  ", password);
        assertThat(login.statusCode()).isEqualTo(200);
        JsonNode body = json(login);
        assertThat(body.path("success").asBoolean()).isTrue();
        assertThat(body.path("data").size()).isEqualTo(1);
        var user = body.path("data").path("user");
        assertThat(user.size()).isEqualTo(9);
        assertThat(user.path("memberId").asLong()).isEqualTo(memberId);
        assertThat(user.path("email").asText()).isEqualTo(email);
        assertThat(user.path("orgId").asLong()).isEqualTo(orgId);
        assertThat(user.path("jurisdictionSidoCode").asText()).isEqualTo("11");
        assertThat(user.path("mustChangePassword").asBoolean()).isFalse();
        assertThat(user.path("title").isNull()).isTrue();
        assertCsrfCookieExpired(login);
        assertThat(login.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");
        assertThat(body.path("meta").path("requestId").asText())
                .isEqualTo(login.headers().firstValue("X-Request-Id").orElseThrow());
        assertThat(!login.body().contains(password)).isTrue();
        String session = sessionId();
        createdSessionIds.add(session);
        org.springframework.session.Session persisted = sessions.findById(session);
        assertThat(persisted.getMaxInactiveInterval()).isEqualTo(Duration.ofHours(2));
        assertThat(jdbc.queryForObject("SELECT principal_name FROM spring_session WHERE session_id = ?",
                String.class, session)).isEqualTo(Long.toString(memberId));
        assertThat(jdbc.queryForObject("SELECT count(*) FROM spring_session_attributes a JOIN spring_session s "
                + "ON s.primary_id = a.session_primary_id WHERE s.session_id = ?", Integer.class, session)).isPositive();
        String attributes = sessionCookieAttributes(login);
        assertThat(attributes).contains("Path=/api", "HttpOnly", "SameSite=Lax").doesNotContain("Domain=", "Secure");

        var initialMe = get("/auth/me");
        assertThat(initialMe.statusCode()).isEqualTo(200);
        assertThat(json(initialMe).path("data").has("title")).isTrue();
        assertThat(json(initialMe).path("data").path("title").isNull()).isTrue();

        jdbc.update("UPDATE member SET name = '변경한 이름', title = '변경한 직함' WHERE member_id = ?", memberId);
        var me = get("/auth/me");
        assertThat(me.statusCode()).isEqualTo(200);
        var profile = json(me).path("data");
        assertThat(profile.size()).isEqualTo(7);
        assertThat(profile.path("name").asText()).isEqualTo("변경한 이름");
        assertThat(profile.path("title").asText()).isEqualTo("변경한 직함");

        var missingCsrf = client.send(request("/auth/logout").POST(HttpRequest.BodyPublishers.noBody()).build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(missingCsrf.statusCode()).isEqualTo(403);
        assertThat(get("/auth/me").statusCode()).isEqualTo(200);
        var logout = post("/auth/logout", null);
        assertThat(logout.statusCode()).isEqualTo(204);
        assertThat(logout.body()).isEmpty();
        assertThat(sessionCookieAttributes(logout)).contains("Max-Age=0");
        assertCsrfCookieExpired(logout);
        assertThat(sessions.findById(session) == null).isTrue();
        assertThat(get("/auth/me").statusCode()).isEqualTo(401);
        assertThat(post("/auth/logout", null).statusCode()).isEqualTo(204);
    }

    @Test
    void reauthenticationRotatesSessionAndOldSessionCannotRestore() throws Exception {
        assertThat(login(email, password).statusCode()).isEqualTo(200);
        String first = sessionId();
        createdSessionIds.add(first);
        String oldCookie = cookies.getCookieStore().getCookies().stream()
                .filter(cookie -> cookie.getName().equals("SESSION")).findFirst().orElseThrow().getValue();
        assertThat(login(email, password).statusCode()).isEqualTo(200);
        String second = sessionId();
        createdSessionIds.add(second);
        assertThat(!first.equals(second)).isTrue();
        assertThat(sessions.findById(first) == null).isTrue();
        assertThat(sessions.findById(second) != null).isTrue();
        var replay = HttpClient.newHttpClient().send(request("/auth/me").header("Cookie", "SESSION=" + oldCookie)
                .GET().build(), HttpResponse.BodyHandlers.ofString());
        assertThat(replay.statusCode()).isEqualTo(401);
    }

    @Test
    void wrongMissingWithdrawnAndExpiredCredentialsHaveIdenticalFailures() throws Exception {
        Set<String> errors = new HashSet<>();
        for (int scenario = 0; scenario < 4; scenario++) {
            if (scenario == 2) jdbc.update("UPDATE member SET withdrawn_at = now() WHERE member_id = ?", memberId);
            if (scenario == 3) jdbc.update("UPDATE member SET withdrawn_at = NULL, "
                    + "temp_password_expires_at = now() - interval '1 second' WHERE member_id = ?", memberId);
            var result = login(scenario == 1 ? "missing-" + email : email, scenario == 0 ? password + "x" : password);
            assertThat(result.statusCode()).isEqualTo(401);
            var error = json(result).path("error");
            assertThat(error.path("code").asText()).isEqualTo("INVALID_CREDENTIALS");
            assertThat(error.path("message").asText()).isEqualTo("이메일 또는 비밀번호가 일치하지 않습니다.");
            errors.add(error.toString());
            assertThat(get("/auth/me").statusCode()).isEqualTo(401);
        }
        assertThat(errors).hasSize(1);
        assertThat(sessions.findByPrincipalName(Long.toString(memberId)).isEmpty()).isTrue();
    }

    @Test
    void temporaryPasswordAllowsMeButDeniesBusinessRequestsAndCanLogout() throws Exception {
        jdbc.update("UPDATE member SET temp_password_expires_at = now() + interval '1 hour' WHERE member_id = ?", memberId);
        var login = login(email, password);
        assertThat(login.statusCode()).isEqualTo(200);
        assertThat(json(login).path("data").path("user").path("mustChangePassword").asBoolean()).isTrue();
        var me = get("/auth/me");
        assertThat(me.statusCode()).isEqualTo(200);
        assertThat(json(me).path("data").path("mustChangePassword").asBoolean()).isTrue();
        var forbidden = get("/regions/sidos");
        assertThat(forbidden.statusCode()).isEqualTo(403);
        assertThat(json(forbidden).path("error").path("code").asText()).isEqualTo("PASSWORD_CHANGE_REQUIRED");
        assertThat(post("/auth/logout", null).statusCode()).isEqualTo(204);
        assertThat(get("/auth/me").statusCode()).isEqualTo(401);
    }

    @Test
    void restrictedSessionRequiresLogoutBeforeLoggingInAsAnotherMember() throws Exception {
        String otherEmail = "switch-" + email;
        String otherPassword = UUID.randomUUID().toString();
        long otherMemberId = jdbc.queryForObject("""
                INSERT INTO member(org_id, email_normalized, name, password_hash)
                VALUES (?, ?, '계정 전환 검사용', ?) RETURNING member_id
                """, Long.class, orgId, otherEmail, passwords.encode(otherPassword));
        try {
            jdbc.update("UPDATE member SET temp_password_expires_at = now() + interval '1 hour' WHERE member_id = ?", memberId);
            assertThat(login(email, password).statusCode()).isEqualTo(200);

            var blocked = login(otherEmail, otherPassword);
            assertThat(blocked.statusCode()).isEqualTo(403);
            assertThat(json(blocked).path("error").path("code").asText()).isEqualTo("PASSWORD_CHANGE_REQUIRED");
            var me = get("/auth/me");
            assertThat(me.statusCode()).isEqualTo(200);
            assertThat(json(me).path("data").path("memberId").asLong()).isEqualTo(memberId);
            assertThat(sessions.findByPrincipalName(Long.toString(otherMemberId)).isEmpty()).isTrue();

            assertThat(post("/auth/logout", null).statusCode()).isEqualTo(204);
            assertThat(login(otherEmail, otherPassword).statusCode()).isEqualTo(200);
            me = get("/auth/me");
            assertThat(me.statusCode()).isEqualTo(200);
            assertThat(json(me).path("data").path("memberId").asLong()).isEqualTo(otherMemberId);
            assertThat(json(me).path("data").path("mustChangePassword").asBoolean()).isFalse();
            assertThat(post("/auth/logout", null).statusCode()).isEqualTo(204);
        } finally {
            sessions.findByPrincipalName(Long.toString(otherMemberId)).keySet().forEach(sessions::deleteById);
            jdbc.update("DELETE FROM member WHERE member_id = ? AND email_normalized = ?", otherMemberId, otherEmail);
        }
    }

    @Test
    void meRejectsAndInvalidatesSessionAfterMemberIsWithdrawn() throws Exception {
        assertThat(login(email, password).statusCode()).isEqualTo(200);
        String session = sessionId();
        createdSessionIds.add(session);
        jdbc.update("UPDATE member SET withdrawn_at = now() WHERE member_id = ?", memberId);
        assertThat(get("/auth/me").statusCode()).isEqualTo(401);
        assertThat(sessions.findById(session) == null).isTrue();
    }

    @Test
    void meInvalidatesRestrictedSessionWhenTemporaryPasswordExpires() throws Exception {
        jdbc.update("UPDATE member SET temp_password_expires_at = now() + interval '1 hour' WHERE member_id = ?", memberId);
        var login = login(email, password);
        assertThat(login.statusCode()).isEqualTo(200);
        assertThat(json(login).path("data").path("user").path("mustChangePassword").asBoolean()).isTrue();
        String session = sessionId();
        createdSessionIds.add(session);
        jdbc.update("UPDATE member SET temp_password_expires_at = now() - interval '1 second' WHERE member_id = ?", memberId);

        var me = get("/auth/me");
        assertThat(me.statusCode()).isEqualTo(401);
        assertThat(json(me).path("error").path("code").asText()).isEqualTo("UNAUTHENTICATED");
        assertThat(sessions.findById(session) == null).isTrue();
        assertThat(sessionCookieAttributes(me)).contains("Max-Age=0");
        assertCsrfCookieExpired(me);
        assertThat(get("/auth/me").statusCode()).isEqualTo(401);
    }

    @Test
    void loginKeepsPasswordSpacesAndCountsUnicodeCodePoints() throws Exception {
        String raw = " " + "\uD83D\uDE00".repeat(126) + " ";
        jdbc.update("UPDATE member SET password_hash = ? WHERE member_id = ?", passwords.encode(raw), memberId);
        assertThat(login(email, raw.strip()).statusCode()).isEqualTo(401);
        assertThat(login(email, raw + "x").statusCode()).isEqualTo(400);
        assertThat(login(email, raw).statusCode()).isEqualTo(200);
    }

    private HttpResponse<String> login(String email, String password) throws Exception {
        return post("/auth/login", mapper.writeValueAsString(Map.of("email", email, "password", password)));
    }

    private HttpResponse<String> post(String path, String body) throws Exception {
        assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
        String token = cookies.getCookieStore().getCookies().stream()
                .filter(c -> c.getName().equals("XSRF-TOKEN")).findFirst().orElseThrow().getValue();
        return client.send(request(path).header("X-XSRF-TOKEN", token).header("Content-Type", "application/json")
                .POST(body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body))
                .build(), HttpResponse.BodyHandlers.ofString());
    }

    private HttpResponse<String> get(String path) throws Exception {
        return client.send(request(path).GET().build(), HttpResponse.BodyHandlers.ofString());
    }

    private HttpRequest.Builder request(String path) {
        return HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api" + path))
                .timeout(Duration.ofSeconds(10));
    }

    private JsonNode json(HttpResponse<String> response) throws Exception {
        return mapper.readTree(response.body());
    }

    private String sessionId() {
        String encoded = cookies.getCookieStore().getCookies().stream()
                .filter(c -> c.getName().equals("SESSION")).findFirst().orElseThrow().getValue();
        return new String(Base64.getDecoder().decode(encoded), StandardCharsets.UTF_8);
    }

    private String sessionCookieAttributes(HttpResponse<String> response) {
        String cookie = response.headers().allValues("Set-Cookie").stream()
                .filter(value -> value.startsWith("SESSION=")).findFirst().orElseThrow();
        return cookie.substring(cookie.indexOf(';') + 1);
    }

    private void assertCsrfCookieExpired(HttpResponse<String> response) {
        // GET에서 먼저 토큰이 발급된 뒤 세션 무효화로 삭제될 수도 있어 마지막 헤더를 검사한다.
        var attributes = response.headers().allValues("Set-Cookie").stream()
                .filter(value -> value.startsWith("XSRF-TOKEN="))
                .map(value -> java.net.HttpCookie.parse(value).getFirst()).toList().getLast();
        assertThat(attributes.getMaxAge()).isZero();
        assertThat(attributes.getPath()).isEqualTo("/");
        assertThat(attributes.getValue().isEmpty()).isTrue();
    }
}
