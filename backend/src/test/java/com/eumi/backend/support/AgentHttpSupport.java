package com.eumi.backend.support;

import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.UUID;
import com.eumi.backend.agent.AgentClient;
import com.eumi.backend.agent.AgentDtos;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.session.jdbc.JdbcIndexedSessionRepository;
import org.springframework.test.context.ActiveProfiles;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.assertThat;

/** 인증은 실제 A1 API를 사용한다. 장애 복구 검사만 AI 클라이언트를 대체한다. */
@Tag("local-integration")
@ActiveProfiles("local")
public abstract class AgentHttpSupport {
    @LocalServerPort protected int port;
    @Autowired protected JdbcTemplate jdbc;
    @Autowired protected JsonMapper json;
    @Autowired protected PasswordEncoder passwords;
    @Autowired protected JdbcIndexedSessionRepository sessions;
    @Autowired protected AgentClient agent;
    protected long orgId;
    protected long memberId;
    protected long otherMemberId;
    protected String email;
    protected String otherEmail;
    protected String password;
    protected Browser browser;

    @BeforeEach
    void setupMembers() throws Exception {
        email = "ai1-" + UUID.randomUUID() + "@eumi.test";
        otherEmail = "other-" + email;
        password = UUID.randomUUID() + "Aa1!";
        orgId = jdbc.queryForObject("INSERT INTO organization(org_name, jurisdiction_sigungu_code, official_domain) "
                + "VALUES ('AI1 synthetic integration', '11680', 'eumi.test') RETURNING org_id", Long.class);
        String hash = passwords.encode(password);
        memberId = createMember(email, hash);
        otherMemberId = createMember(otherEmail, hash);
        browser = signIn(email);
    }

    private long createMember(String email, String hash) {
        return jdbc.queryForObject("INSERT INTO member(org_id, email_normalized, name, password_hash) "
                + "VALUES (?, ?, 'AI1 검사용', ?) RETURNING member_id", Long.class, orgId, email, hash);
    }

    protected Browser signIn(String email) throws Exception {
        var result = new Browser();
        var response = result.post("/auth/login", json.writeValueAsString(java.util.Map.of("email", email, "password", password)));
        assertThat(response.statusCode()).isEqualTo(200);
        return result;
    }

    @AfterEach
    void cleanupMembers() {
        for (UUID id : jdbc.queryForList("SELECT conversation_id FROM ai_conversation WHERE member_id IN (?, ?)", UUID.class, memberId, otherMemberId)) {
            try { agent.cancel(id); } catch (RuntimeException ignored) { }
        }
        for (long id : new long[]{memberId, otherMemberId}) {
            sessions.findByPrincipalName(Long.toString(id)).keySet().forEach(sessions::deleteById);
        }
        jdbc.update("DELETE FROM ai_conversation WHERE member_id IN (?, ?)", memberId, otherMemberId);
        jdbc.update("DELETE FROM member WHERE org_id = ? AND email_normalized IN (?, ?)", orgId, email, otherEmail);
        jdbc.update("DELETE FROM organization WHERE org_id = ? AND org_name = 'AI1 synthetic integration'", orgId);
    }

    protected String question(UUID id, String text) { return json.writeValueAsString(new AgentDtos.QuestionRequest(id, text)); }
    protected JsonNode body(HttpResponse<String> response) { return json.readTree(response.body()); }
    protected String messagesPath(UUID id) { return "/agent/conversations/" + id + "/messages"; }
    protected String cancelPath(UUID id) { return "/agent/conversations/" + id + "/cancel"; }
    protected UUID conversation(JsonNode created) { return UUID.fromString(created.path("data").path("conversationId").asText()); }

    protected JsonNode awaitEnd(UUID id) throws Exception {
        long deadline = System.nanoTime() + Duration.ofSeconds(8).toNanos();
        do {
            var response = browser.get(messagesPath(id));
            assertThat(response.statusCode()).isEqualTo(200);
            for (var row : body(response).path("data").path("messages")) {
                if (java.util.Set.of("완료", "실패", "취소").contains(row.path("status").asText())) return row;
            }
            Thread.sleep(30);
        } while (System.nanoTime() < deadline);
        throw new AssertionError("AI terminal message did not arrive within test deadline.");
    }

    protected UUID pendingConversation(long ageMillis) {
        UUID id = UUID.randomUUID();
        jdbc.update("INSERT INTO ai_conversation(conversation_id, member_id) VALUES (?, ?)", id, memberId);
        jdbc.update("INSERT INTO ai_message(conversation_id, role, status, content, created_at) "
                + "VALUES (?, 'Member', '질문', '장애 복구 검사', now() - (? * interval '1 millisecond'))", id, ageMillis);
        return id;
    }

    protected long pendingQuestion(UUID id) {
        return jdbc.queryForObject("SELECT message_id FROM ai_message WHERE conversation_id = ? AND status = '질문'", Long.class, id);
    }

    protected class Browser {
        public Browser() { }
        private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
        private final HttpClient client = HttpClient.newBuilder().cookieHandler(cookies).connectTimeout(Duration.ofSeconds(3)).build();
        public HttpResponse<String> get(String path) throws Exception {
            return client.send(request(path).GET().build(), HttpResponse.BodyHandlers.ofString());
        }
        public HttpResponse<String> post(String path, String body) throws Exception {
            assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
            String token = cookies.getCookieStore().getCookies().stream().filter(c -> c.getName().equals("XSRF-TOKEN"))
                    .findFirst().orElseThrow().getValue();
            return client.send(request(path).header("X-XSRF-TOKEN", token).header("Content-Type", "application/json")
                    .POST(body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body)).build(),
                    HttpResponse.BodyHandlers.ofString());
        }
        private HttpRequest.Builder request(String path) {
            return HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api" + path)).timeout(Duration.ofSeconds(5));
        }
    }
}
