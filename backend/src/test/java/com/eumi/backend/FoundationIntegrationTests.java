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
import java.util.List;
import java.util.UUID;

import com.eumi.backend.common.mail.MailService;
import com.eumi.backend.support.FoundationFixture;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.session.jdbc.JdbcIndexedSessionRepository;
import org.springframework.test.context.ActiveProfiles;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;

/** 실제 PostgreSQL·HTTP·Mailpit 사용. 인증 자체만 src/test fixture로 대체한다. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Import(FoundationFixture.class)
class FoundationIntegrationTests {
    @LocalServerPort int port;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired JdbcTemplate jdbc;
    @Autowired MailService mail;
    @Autowired JsonMapper mapper;
    private CookieManager cookies;
    private HttpClient client;
    private final List<String> createdSessionIds = new ArrayList<>();

    @BeforeEach
    void client() {
        cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        client = HttpClient.newBuilder().cookieHandler(cookies).connectTimeout(Duration.ofSeconds(5)).build();
    }

    @AfterEach
    void cleanOnlyCreatedSessions() {
        createdSessionIds.forEach(sessions::deleteById);
    }

    @Test
    void jdbcSessionPersistsRestoresAndRotatesThroughRealHttp() throws Exception {
        var login = signIn();
        String first = sessionId();
        createdSessionIds.add(first);
        org.springframework.session.Session session = sessions.findById(first);
        assertThat(session).isNotNull();
        assertThat(session.getMaxInactiveInterval()).isEqualTo(Duration.ofHours(2));
        assertThat(jdbc.queryForObject("SELECT principal_name FROM spring_session WHERE session_id = ?",
                String.class, first)).isEqualTo("910000001");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM spring_session_attributes a JOIN spring_session s "
                + "ON s.primary_id = a.session_primary_id WHERE s.session_id = ?", Integer.class, first)).isPositive();

        String attributes = login.headers().allValues("Set-Cookie").stream()
                .filter(c -> c.startsWith("SESSION=")).findFirst().orElseThrow();
        attributes = attributes.substring(attributes.indexOf(';') + 1);
        assertThat(attributes).contains("Path=/api", "HttpOnly", "SameSite=Lax").doesNotContain("Domain=", "Secure");

        var restored = get("/auth/me");
        assertThat(restored.statusCode()).isEqualTo(200);
        assertThat(mapper.readTree(restored.body()).path("data").asText()).isEqualTo("910000001");

        signIn();
        String second = sessionId();
        createdSessionIds.add(second);
        assertThat(second.equals(first)).isFalse();
        assertThat(sessions.findById(first)).isNull();
        assertThat(sessions.findById(second)).isNotNull();
        sessions.deleteById(second);
        assertThat(get("/auth/me").statusCode()).isEqualTo(401);
    }

    @Test
    void actualHttpPreservesHealthCsrfAndUnauthorizedContracts() throws Exception {
        var csrf = get("/auth/csrf");
        var health = get("/health");
        assertThat(health.statusCode()).isEqualTo(200);
        assertThat(mapper.readTree(health.body()).path("status").asText()).isEqualTo("UP");
        assertThat(mapper.readTree(health.body()).has("success")).isFalse();
        var unauthorized = get("/auth/me");
        assertThat(unauthorized.statusCode()).isEqualTo(401);
        JsonNode json = mapper.readTree(unauthorized.body());
        assertThat(json.path("error").path("code").asText()).isEqualTo("UNAUTHENTICATED");
        assertThat(unauthorized.headers().firstValue("X-Request-Id").orElseThrow())
                .isEqualTo(json.path("meta").path("requestId").asText());
        assertThat(csrf.statusCode()).isEqualTo(204);
        assertThat(csrf.body()).isEmpty();
        String attributes = csrf.headers().allValues("Set-Cookie").stream()
                .filter(c -> c.startsWith("XSRF-TOKEN=")).findFirst().orElseThrow();
        attributes = attributes.substring(attributes.indexOf(';') + 1);
        assertThat(attributes).contains("Path=/", "SameSite=Lax").doesNotContain("HttpOnly", "Domain=", "Secure");
        assertThat(get("/auth/csrf").statusCode()).isEqualTo(204); // 기존 유효 쿠키가 있으면 재설정 헤더는 생략 가능하다.
        var missing = client.send(request("/auth/login").POST(HttpRequest.BodyPublishers.noBody()).build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(missing.statusCode()).isEqualTo(403);
        assertThat(mapper.readTree(missing.body()).path("error").path("code").asText()).isEqualTo("CSRF_INVALID");
    }

    @Test
    void actualMailpitReceivesSyntheticMessage() throws Exception {
        String subject = "G1 foundation smoke " + UUID.randomUUID();
        String text = "G1 synthetic integration message. No personal data.";
        mail.sendPlainText("foundation-fixture@eumi.test", subject, text);
        HttpClient mailbox = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
        String id = null;
        for (int attempt = 0; attempt < 20 && id == null; attempt++) {
            var result = mailbox.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:8025/api/v1/messages?limit=50"))
                    .timeout(Duration.ofSeconds(5)).GET().build(), HttpResponse.BodyHandlers.ofString());
            assertThat(result.statusCode()).isEqualTo(200);
            for (JsonNode message : mapper.readTree(result.body()).path("messages")) {
                if (subject.equals(message.path("Subject").asText())) id = message.path("ID").asText();
            }
            if (id == null) Thread.sleep(100);
        }
        assertThat(id != null).isTrue();
        var received = mailbox.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:8025/api/v1/message/" + id))
                .timeout(Duration.ofSeconds(5)).GET().build(), HttpResponse.BodyHandlers.ofString());
        assertThat(received.statusCode()).isEqualTo(200);
        assertThat(mapper.readTree(received.body()).path("Text").asText().strip()).isEqualTo(text);
        // 메일함에서 사람이 확인할 수 있게 이 테스트 메일은 유지한다.
    }

    private HttpResponse<String> signIn() throws Exception {
        get("/auth/csrf");
        String token = cookies.getCookieStore().getCookies().stream()
                .filter(c -> c.getName().equals("XSRF-TOKEN")).findFirst().orElseThrow().getValue();
        var response = client.send(request("/auth/login").header("X-XSRF-TOKEN", token)
                .POST(HttpRequest.BodyPublishers.noBody()).build(), HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).isEqualTo(204);
        return response;
    }

    private String sessionId() {
        String value = cookies.getCookieStore().getCookies().stream()
                .filter(c -> c.getName().equals("SESSION")).findFirst().orElseThrow().getValue();
        return new String(Base64.getDecoder().decode(value), StandardCharsets.UTF_8);
    }

    private HttpResponse<String> get(String path) throws Exception {
        return client.send(request(path).GET().build(), HttpResponse.BodyHandlers.ofString());
    }

    private HttpRequest.Builder request(String path) {
        return HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api" + path))
                .timeout(Duration.ofSeconds(5));
    }
}
