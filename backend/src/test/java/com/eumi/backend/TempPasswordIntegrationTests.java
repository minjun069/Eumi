package com.eumi.backend;

import java.net.*;
import java.net.http.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Pattern;
import com.eumi.backend.auth.password.TempPasswordRepository;
import com.eumi.backend.support.MailpitTestInbox;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mail.MailSendException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.session.jdbc.JdbcIndexedSessionRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** 실제 PostgreSQL·SMTP·Mailpit API·A1 세션·8080. 고유 fixture만 정리한다. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.DEFINED_PORT,
        properties = {"server.port=8080", "eumi.ai.mode=fake", "spring.datasource.hikari.minimum-idle=1"})
class TempPasswordIntegrationTests {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired JsonMapper json;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired Clock clock;
    @MockitoSpyBean PasswordEncoder passwords;
    @MockitoSpyBean TempPasswordRepository repository;
    @MockitoSpyBean JavaMailSender sender;
    private final String marker = "a3-temp-" + UUID.randomUUID();
    private final Map<Long,String> emails = new HashMap<>();
    private final Set<String> mailRecipients = new HashSet<>();
    private long org, member, other;
    private String original;
    private Browser browser;
    private MailpitTestInbox inbox;

    @BeforeEach void setup() throws Exception {
        inbox = new MailpitTestInbox(json);
        org = jdbc.queryForObject("INSERT INTO public.organization(org_name,jurisdiction_sigungu_code,official_domain) "
                + "VALUES (?,'11680','eumi.test') RETURNING org_id", Long.class, marker);
        original = UUID.randomUUID() + "Aa2!";
        String hash = passwords.encode(original);
        member = createMember(hash); other = createMember(hash);
        browser = login(member, original);
    }
    private long createMember(String hash) {
        String email = "a3-temp-" + UUID.randomUUID() + "@eumi.test";
        long id = jdbc.queryForObject("INSERT INTO public.member(org_id,email_normalized,name,password_hash) VALUES (?,?,?,?) RETURNING member_id",
                Long.class, org, email, marker, hash);
        emails.put(id,email); mailRecipients.add(email); return id;
    }
    @AfterEach void cleanupOwnedFixtures() throws Exception {
        reset(repository,passwords,sender);
        try {
            for (long id : emails.keySet()) {
                sessions.findByPrincipalName(Long.toString(id)).keySet().forEach(sessions::deleteById);
                jdbc.update("DELETE FROM public.member WHERE member_id=? AND org_id=? AND name=?", id, org, marker);
            }
            if (org != 0) jdbc.update("DELETE FROM public.organization WHERE org_id=? AND org_name=?",org,marker);
        } finally { if (inbox != null) inbox.deleteOwned(mailRecipients); }
    }
    private Browser login(long id, String password) throws Exception {
        var result = new Browser();
        assertThat(result.post("/auth/login", Map.of("email",emails.get(id),"password",password)).statusCode()).isEqualTo(200);
        return result;
    }
    private Map<String,Object> input() { return Map.of("email",emails.get(member),"name",marker); }
    private Snapshot snapshot() {
        return jdbc.queryForObject("SELECT password_hash,temp_password_expires_at,updated_at FROM public.member WHERE member_id=?",
                (rs,row) -> {
                    var expiry = rs.getObject(2,OffsetDateTime.class);
                    return new Snapshot(rs.getString(1), expiry == null ? null : expiry.toInstant(),rs.getObject(3,OffsetDateTime.class).toInstant());
                },member);
    }
    private record Snapshot(String hash, Instant expires, Instant updated) {
        @Override public String toString() { return "Snapshot[redacted]"; }
    }
    private long sessionCount(long id) { return jdbc.queryForObject("SELECT count(*) FROM public.spring_session WHERE principal_name=?",Long.class,Long.toString(id)); }
    private HttpResponse<String> issue(Object input) throws Exception { return new Browser().post("/auth/temp-password",input); }
    private void accepted(HttpResponse<String> response) {
        assertThat(response.statusCode()).isEqualTo(204); assertThat(response.body()).isEmpty();
        assertThat(response.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");
        UUID.fromString(response.headers().firstValue("X-Request-Id").orElseThrow());
    }
    private String temporaryPasswordFromOnlyOwnedMail() throws Exception {
        long deadline = System.nanoTime() + Duration.ofSeconds(5).toNanos();
        List<String> ids;
        do {
            ids = inbox.ids(Set.of(emails.get(member)));
            if (!ids.isEmpty()) break;
            Thread.sleep(40);
        } while (System.nanoTime() < deadline);
        assertThat(ids.size()).isEqualTo(1);
        var message = inbox.message(ids.getFirst());
        assertThat(message.path("Subject").asText()).isEqualTo("[이음이] 임시 비밀번호 안내");
        String text = message.path("Text").asText();
        var match = Pattern.compile("(?m)^임시 비밀번호: ([^\\r\\n]+)").matcher(text);
        assertThat(match.find()).isTrue();
        String temporary = match.group(1);
        assertThat(temporary.matches("[A-HJ-NP-Za-km-np-z2-9!@#$%^&*]{12}")).isTrue();
        var expiry = snapshot().expires();
        String formatted = DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss XXX '(서울)'")
                .withZone(ZoneId.of("Asia/Seoul")).format(expiry);
        assertThat(text.contains(formatted) && text.contains("24시간") && text.contains("바로 비밀번호를 변경")).isTrue();
        assertThat(text.contains(marker) || text.contains(emails.get(member))).isFalse();
        return temporary;
    }

    @Test void issueFromMailpitLogsInRestrictedAndRevokesAllOwnedSessionsThrough8080() throws Exception {
        assertThat(port).isEqualTo(8080);
        var second = login(member,original); var unrelated = login(other,original);
        var before = snapshot(); Instant start = clock.instant();
        accepted(issue(Map.of("email","  " + emails.get(member).toUpperCase(Locale.ROOT) + "  ","name","  " + marker + "  ")));
        var after = snapshot();
        assertThat(after.hash().equals(before.hash())).isFalse();
        assertThat(after.expires()).isBetween(start.plus(Duration.ofHours(24)),clock.instant().plus(Duration.ofHours(24)));
        assertThat(Duration.between(after.updated(),after.expires())).isEqualTo(Duration.ofHours(24));
        assertThat(sessionCount(member)).isZero(); assertThat(sessionCount(other)).isEqualTo(1);
        error(browser.get("/auth/me"),401,"UNAUTHENTICATED"); error(second.get("/auth/me"),401,"UNAUTHENTICATED");
        assertThat(unrelated.get("/auth/me").statusCode()).isEqualTo(200);
        String temporary = temporaryPasswordFromOnlyOwnedMail();
        assertThat(passwords.matches(temporary,after.hash())).isTrue();
        var restricted = new Browser();
        var login = restricted.post("/auth/login",Map.of("email",emails.get(member),"password",temporary));
        assertThat(login.statusCode()).isEqualTo(200);
        assertThat(body(login).path("data").path("user").path("mustChangePassword").asBoolean()).isTrue();
        error(restricted.get("/members/me"),403,"PASSWORD_CHANGE_REQUIRED");
        error(new Browser().post("/auth/login",Map.of("email",emails.get(member),"password",original)),401,"INVALID_CREDENTIALS");
        String changed = UUID.randomUUID() + "Bb3@";
        var change = restricted.send("PUT","/members/me/password",Map.of("currentPassword",temporary,"newPassword",changed));
        assertThat(change.statusCode()).isEqualTo(200);
        assertThat(body(change).path("data").path("user").path("mustChangePassword").asBoolean()).isFalse();
        assertThat(snapshot().expires()).isNull(); assertThat(restricted.get("/members/me").statusCode()).isEqualTo(200);
    }
    @Test void unknownMismatchedAndWithdrawnRequestsDoNotChangeDatabaseMailOrSessions() throws Exception {
        String missing = "a3-temp-" + UUID.randomUUID() + "@eumi.test"; mailRecipients.add(missing);
        var before = snapshot(); long sessionsBefore = sessionCount(member);
        accepted(issue(Map.of("email",missing,"name",marker)));
        accepted(issue(Map.of("email",emails.get(member),"name",marker+" wrong")));
        assertThat(snapshot().equals(before)).isTrue();
        jdbc.update("UPDATE public.member SET withdrawn_at=now() WHERE member_id=?",member);
        accepted(issue(input()));
        assertThat(snapshot().equals(before)).isTrue();
        assertThat(sessionCount(member)).isEqualTo(sessionsBefore);
        assertThat(inbox.ids(mailRecipients).size()).isZero();
    }
    @Test void requestWithin24HoursLeavesExistingTemporaryPasswordMailAndSessionsUnchanged() throws Exception {
        accepted(issue(input())); String temporary = temporaryPasswordFromOnlyOwnedMail();
        login(member,temporary);
        var before = snapshot(); long sessionsBefore = sessionCount(member);
        var ids = inbox.ids(mailRecipients);
        accepted(issue(input()));
        assertThat(snapshot().equals(before)).isTrue();
        assertThat(sessionCount(member)).isEqualTo(sessionsBefore);
        assertThat(inbox.ids(mailRecipients)).isEqualTo(ids);
    }
    @Test void expiredTemporaryPasswordCanBeReissued() throws Exception {
        jdbc.update("UPDATE public.member SET temp_password_expires_at=now()-interval '1 second' WHERE member_id=?",member);
        accepted(issue(input())); String temporary = temporaryPasswordFromOnlyOwnedMail();
        assertThat(login(member,temporary).get("/auth/me").statusCode()).isEqualTo(200);
    }
    @Test void smtpFailureRollsBackPasswordExpiryUpdatedAtAndSessionDeletion() throws Exception {
        var second = login(member,original); var before = snapshot(); long sessionsBefore = sessionCount(member);
        doThrow(new MailSendException("synthetic-mail-unavailable")).when(sender).send(any(SimpleMailMessage.class));
        error(issue(input()),500,"INTERNAL_SERVER_ERROR");
        assertThat(snapshot().equals(before)).isTrue();
        assertThat(sessionCount(member)).isEqualTo(sessionsBefore);
        assertThat(browser.get("/auth/me").statusCode()).isEqualTo(200);
        assertThat(second.get("/auth/me").statusCode()).isEqualTo(200);
        assertThat(inbox.ids(mailRecipients).size()).isZero();
    }
    @Test void hashingAlwaysRunsOnceOutsideTransactionAndConnectionIncludingMissingMember() throws Exception {
        var encodes = new AtomicInteger(); var wrongBoundary = new AtomicInteger();
        doAnswer(call -> {
            encodes.incrementAndGet();
            if (TransactionSynchronizationManager.isActualTransactionActive() || TransactionSynchronizationManager.hasResource(jdbc.getDataSource())) wrongBoundary.incrementAndGet();
            return call.callRealMethod();
        }).when(passwords).encode(anyString());
        String missing = "a3-temp-" + UUID.randomUUID() + "@eumi.test"; mailRecipients.add(missing);
        accepted(issue(Map.of("email",missing,"name",marker)));
        assertThat(encodes.get()).isEqualTo(1);
        accepted(issue(input()));
        assertThat(encodes.get()).isEqualTo(2);
        assertThat(wrongBoundary.get()).isZero();
        assertThat(inbox.ids(mailRecipients).size()).isEqualTo(1);
    }
    @Test void identityChangedBeforeLockIsRecheckedWithoutIssuance() throws Exception {
        doAnswer(call -> {
            jdbc.update("UPDATE public.member SET withdrawn_at=now() WHERE member_id=?",member);
            return call.callRealMethod();
        }).when(repository).lockMember(member);
        var before = snapshot(); accepted(issue(input()));
        assertThat(snapshot().equals(before)).isTrue();
        assertThat(sessionCount(member)).isEqualTo(1);
        assertThat(inbox.ids(mailRecipients).size()).isZero();
    }
    @Test void concurrentRequestsOnlyIssueOneMailAndOnePassword() throws Exception {
        var executor = Executors.newFixedThreadPool(2);
        try {
            var first = executor.submit(() -> issue(input())); var second = executor.submit(() -> issue(input()));
            accepted(first.get(10,TimeUnit.SECONDS)); accepted(second.get(10,TimeUnit.SECONDS));
            assertThat(inbox.ids(mailRecipients).size()).isEqualTo(1);
            String temporary = temporaryPasswordFromOnlyOwnedMail();
            assertThat(passwords.matches(temporary,snapshot().hash())).isTrue();
        } finally { executor.shutdownNow(); }
    }
    @Test void waitsForAnotherTransactionAndRechecksCommittedTemporaryExpiry() throws Exception {
        var before = snapshot(); long sessionsBefore = sessionCount(member);
        var entered = new CountDownLatch(1);
        var requestPid = new AtomicInteger();
        doAnswer(call -> {
            requestPid.set(jdbc.queryForObject("SELECT pg_backend_pid()",Integer.class));
            entered.countDown();
            return call.callRealMethod();
        }).when(repository).lockMember(member);

        var executor = Executors.newSingleThreadExecutor();
        Future<HttpResponse<String>> pending = null;
        try (var blocker = jdbc.getDataSource().getConnection()) {
            blocker.setAutoCommit(false);
            int blockerPid;
            try (var statement = blocker.createStatement(); var row = statement.executeQuery("SELECT pg_backend_pid()")) {
                row.next(); blockerPid = row.getInt(1);
            }
            try (var statement = blocker.prepareStatement("SELECT member_id FROM public.member WHERE member_id=? FOR UPDATE")) {
                statement.setLong(1,member);
                try (var row = statement.executeQuery()) { assertThat(row.next()).isTrue(); }
            }
            Instant committedExpiry;
            try (var statement = blocker.prepareStatement("UPDATE public.member SET temp_password_expires_at=? WHERE member_id=? RETURNING temp_password_expires_at")) {
                statement.setObject(1,clock.instant().plusSeconds(3600).atOffset(ZoneOffset.UTC)); statement.setLong(2,member);
                try (var row = statement.executeQuery()) {
                    assertThat(row.next()).isTrue(); committedExpiry = row.getObject(1,OffsetDateTime.class).toInstant();
                }
            }
            // 별도 연결의 미커밋 값은 초기 조회에 보이지 않는다. 해시 뒤 잠금 진입을 기다린다.
            pending = executor.submit(() -> issue(input()));
            assertThat(entered.await(5,TimeUnit.SECONDS)).as("request reached the lock after initial lookup and hashing").isTrue();
            assertThat(requestPid.get()).isNotEqualTo(blockerPid);
            assertThat(awaitBlockedSelect(requestPid.get(),blockerPid)).as("SELECT FOR UPDATE waits for the other transaction").isTrue();
            boolean completed = false;
            try { pending.get(300,TimeUnit.MILLISECONDS); completed = true; }
            catch (TimeoutException expected) { }
            assertThat(completed).as("request must remain pending while the row lock is held").isFalse();

            blocker.commit();
            accepted(pending.get(10,TimeUnit.SECONDS));
            assertThat(snapshot().equals(new Snapshot(before.hash(),committedExpiry,before.updated()))).isTrue();
            assertThat(sessionCount(member)).isEqualTo(sessionsBefore);
            assertThat(inbox.ids(mailRecipients).size()).isZero();
        } finally {
            // blocker가 닫히며 미커밋 변경을 롤백한 뒤 요청 종료를 기다리고 fixture를 정리한다.
            if (pending != null) {
                try { pending.get(10,TimeUnit.SECONDS); }
                catch (InterruptedException ex) { Thread.currentThread().interrupt(); pending.cancel(true); }
                catch (ExecutionException | TimeoutException ex) { pending.cancel(true); }
            }
            executor.shutdownNow();
        }
    }
    private boolean awaitBlockedSelect(int requestPid,int blockerPid) throws Exception {
        long deadline = System.nanoTime() + Duration.ofSeconds(3).toNanos();
        do {
            boolean blocked = Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                    + "WHERE pid=? AND wait_event_type='Lock' AND upper(query) LIKE '%FOR UPDATE%' "
                    + "AND ?=ANY(pg_blocking_pids(pid)))",Boolean.class,requestPid,blockerPid));
            if (blocked) return true;
            Thread.sleep(10);
        } while (System.nanoTime() < deadline);
        return false;
    }
    @Test void authenticatedRequesterAlsoLosesOwnSessionWithoutResurrection() throws Exception {
        accepted(browser.post("/auth/temp-password",input()));
        assertThat(sessionCount(member)).isZero();
        error(browser.get("/auth/me"),401,"UNAUTHENTICATED");
        assertThat(inbox.ids(mailRecipients).size()).isEqualTo(1);
    }
    @Test void csrfAndMalformedRequestsDoNotIssueMailOrChangePassword() throws Exception {
        var before = snapshot(); var anonymous = new Browser();
        error(anonymous.withoutCsrf("/auth/temp-password",input()),403,"CSRF_INVALID");
        error(issue(Map.of("email","bad","name",marker)),400,"VALIDATION_ERROR");
        error(issue(Map.of("email",emails.get(member),"name",marker,"extra",true)),400,"INVALID_JSON");
        assertThat(snapshot().equals(before)).isTrue();
        assertThat(sessionCount(member)).isEqualTo(1);
        assertThat(inbox.ids(mailRecipients).size()).isZero();
    }
    @Test void fullWidthSpaceIsRetainedLikeLoginAndDoesNotResetThePlainEmailAccount() throws Exception {
        var before = snapshot(); long sessionsBefore = sessionCount(member);
        String email = Character.toString(0x3000) + emails.get(member) + Character.toString(0x3000);
        accepted(issue(Map.of("email",email,"name",marker)));
        error(new Browser().post("/auth/login",Map.of("email",email,"password",original)),401,"INVALID_CREDENTIALS");
        assertThat(snapshot().equals(before)).isTrue();
        assertThat(sessionCount(member)).isEqualTo(sessionsBefore);
        assertThat(inbox.ids(mailRecipients).size()).isZero();
    }
    private JsonNode body(HttpResponse<String> response) { return json.readTree(response.body()); }
    private void error(HttpResponse<String> response, int status, String code) {
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(body(response).path("error").path("code").asText()).isEqualTo(code);
        assertThat(response.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");
    }
    private class Browser {
        private final CookieManager cookies = new CookieManager(null,CookiePolicy.ACCEPT_ALL);
        private final HttpClient http = HttpClient.newBuilder().cookieHandler(cookies).build();
        HttpResponse<String> get(String path) throws Exception { return send("GET",path,null); }
        HttpResponse<String> post(String path,Object input) throws Exception { return send("POST",path,input); }
        HttpResponse<String> send(String method,String path,Object input) throws Exception {
            var request = request(path);
            if (!method.equals("GET")) {
                assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
                String token = cookies.getCookieStore().getCookies().stream().filter(c -> c.getName().equals("XSRF-TOKEN")).findFirst().orElseThrow().getValue();
                request.header("X-XSRF-TOKEN",token);
            }
            return execute(request,method,input);
        }
        HttpResponse<String> withoutCsrf(String path,Object input) throws Exception { return execute(request(path),"POST",input); }
        private HttpRequest.Builder request(String path) {
            return HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api"+path)).timeout(Duration.ofSeconds(10));
        }
        private HttpResponse<String> execute(HttpRequest.Builder request,String method,Object input) throws Exception {
            if (input != null) request.header("Content-Type","application/json");
            return http.send(request.method(method,input == null ? HttpRequest.BodyPublishers.noBody()
                    : HttpRequest.BodyPublishers.ofString(json.writeValueAsString(input))).build(),HttpResponse.BodyHandlers.ofString());
        }
    }
}
