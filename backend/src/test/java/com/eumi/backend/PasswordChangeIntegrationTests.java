package com.eumi.backend;

import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import com.eumi.backend.auth.password.PasswordChangeRepository;
import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.error.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.session.Session;
import org.springframework.session.jdbc.JdbcIndexedSessionRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties="spring.datasource.hikari.minimum-idle=1")
class PasswordChangeIntegrationTests {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired JsonMapper json;
    @MockitoSpyBean PasswordEncoder passwords;
    @MockitoSpyBean PasswordChangeRepository repository;
    private final String marker="password-"+UUID.randomUUID().toString().substring(0,10);
    private final Map<Long,String> emails=new HashMap<>();
    private long org,caller,other;
    private String original,next;
    private Browser browser;

    @BeforeEach
    void setup()throws Exception {
        org=jdbc.queryForObject("INSERT INTO public.organization(org_name,jurisdiction_sigungu_code,official_domain) VALUES (?,'11680','eumi.test') RETURNING org_id",Long.class,marker);
        original=UUID.randomUUID()+"Aa1!";next=UUID.randomUUID()+"Bb2@";
        String hash=passwords.encode(original);caller=member(hash);other=member(hash);browser=login(caller,original);
    }
    private long member(String hash) {
        String email="password-"+UUID.randomUUID()+"@eumi.test";
        long id=jdbc.queryForObject("INSERT INTO public.member(org_id,email_normalized,name,password_hash) VALUES (?,?,?,?) RETURNING member_id",Long.class,org,email,marker+" member",hash);emails.put(id,email);return id;
    }
    private Browser login(long member,String password)throws Exception {
        var b=new Browser();assertThat(b.send("POST","/auth/login",Map.of("email",emails.get(member),"password",password)).statusCode()).isEqualTo(200);return b;
    }
    @AfterEach
    void cleanupOwnedRows() {
        reset(repository,passwords);
        for(long member:emails.keySet()) {
            sessions.findByPrincipalName(Long.toString(member)).keySet().forEach(sessions::deleteById);
            jdbc.update("DELETE FROM public.member WHERE member_id=? AND org_id=? AND name=?",member,org,marker+" member");
        }
        if(org!=0)jdbc.update("DELETE FROM public.organization WHERE org_id=? AND org_name=?",org,marker);
    }
    private Map<String,Object> input(String current,String replacement) {return new HashMap<>(Map.of("currentPassword",current,"newPassword",replacement));}
    private String hash() {return jdbc.queryForObject("SELECT password_hash FROM public.member WHERE member_id=?",String.class,caller);}
    private long sessionCount(long member) {return jdbc.queryForObject("SELECT count(*) FROM public.spring_session WHERE principal_name=?",Long.class,Long.toString(member));}

    @Test
    void normalChangeRotatesCurrentSessionRevokesOnlyOtherSessionsAndPersistsPrincipal()throws Exception {
        var second=login(caller,original);var third=login(caller,original);var unrelated=login(other,original);
        String old=browser.id(),oldHash=hash();assertThat(sessionCount(caller)).isEqualTo(3);
        jdbc.update("UPDATE public.member SET updated_at=TIMESTAMPTZ '2000-01-01 00:00:00+09' WHERE member_id=?",caller);
        var response=browser.send("PUT","/members/me/password",input(original,next));var data=data(response);
        assertThat(data.size()).isEqualTo(1);var user=data.path("user");assertThat(user.size()).isEqualTo(9);
        assertThat(user.path("memberId").asLong()).isEqualTo(caller);assertThat(user.has("title") && user.path("title").isNull()).isTrue();
        assertThat(user.path("mustChangePassword").asBoolean()).isFalse();assertThat(browser.id().equals(old)).isFalse();
        assertThat(sessions.findById(old)==null).isTrue();assertThat(sessionCount(caller)).isEqualTo(1);
        assertThat(hash().equals(oldHash)).isFalse();assertThat(hash().startsWith("{pbkdf2}")).isTrue();assertThat(passwords.matches(next,hash())).isTrue();
        assertThat(jdbc.queryForObject("SELECT temp_password_expires_at IS NULL AND updated_at>TIMESTAMPTZ '2000-01-01 00:00:00+09' FROM public.member WHERE member_id=?",Boolean.class,caller)).isTrue();
        Session saved=sessions.findById(browser.id());assertThat(saved!=null).isTrue();
        SecurityContext context=saved.getAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY);
        var principal=(SessionPrincipal)context.getAuthentication().getPrincipal();assertThat(principal.memberId()).isEqualTo(caller);assertThat(principal.mustChangePassword()).isFalse();
        assertThat(data(browser.get("/auth/me")).path("memberId").asLong()).isEqualTo(caller);
        error(second.get("/auth/me"),401,"UNAUTHENTICATED");error(third.get("/auth/me"),401,"UNAUTHENTICATED");
        error(withSession(old).get("/auth/me"),401,"UNAUTHENTICATED");assertThat(data(unrelated.get("/auth/me")).path("memberId").asLong()).isEqualTo(other);
        error(new Browser().send("POST","/auth/login",Map.of("email",emails.get(caller),"password",original)),401,"INVALID_CREDENTIALS");
        assertThat(data(login(caller,next).get("/auth/me")).path("mustChangePassword").asBoolean()).isFalse();
        assertCsrfExpired(response);
        var cookie=response.headers().allValues("Set-Cookie").stream().filter(v->v.startsWith("SESSION=")).map(v->HttpCookie.parse(v).getFirst()).findFirst().orElseThrow();
        assertThat(cookie.getPath()).isEqualTo("/api");assertThat(cookie.isHttpOnly()).isTrue();
    }
    @Test
    void temporaryPasswordChangeClearsRestrictionAndOtherRestrictedSessions()throws Exception {
        jdbc.update("UPDATE public.member SET temp_password_expires_at=now()+interval '1 hour' WHERE member_id=?",caller);
        var restricted=login(caller,original);var another=login(caller,original);
        error(restricted.get("/members/me"),403,"PASSWORD_CHANGE_REQUIRED");String old=restricted.id();
        assertThat(data(restricted.send("PUT","/members/me/password",input(original,next))).path("user").path("mustChangePassword").asBoolean()).isFalse();
        assertThat(restricted.id().equals(old)).isFalse();assertThat(data(restricted.get("/auth/me")).path("mustChangePassword").asBoolean()).isFalse();
        assertThat(data(restricted.get("/members/me")).size()).isEqualTo(6);
        assertThat(data(restricted.get("/members/me/resources")).path("totalCount").asLong()).isZero();
        error(another.get("/auth/me"),401,"UNAUTHENTICATED");error(browser.get("/auth/me"),401,"UNAUTHENTICATED");
    }
    @Test
    void mismatchAndExpiredTemporaryPasswordUseSame400WithoutRotationOrRevocation()throws Exception {
        var second=login(caller,original);String old=browser.id(),oldHash=hash();
        var mismatch=error(browser.send("PUT","/members/me/password",input(UUID.randomUUID().toString(),next)),400,"CURRENT_PASSWORD_MISMATCH");
        assertThat(mismatch.path("message").asText()).isEqualTo("현재 비밀번호가 일치하지 않습니다.");
        assertThat(browser.id().equals(old)).isTrue();assertThat(hash().equals(oldHash)).isTrue();assertThat(sessionCount(caller)).isEqualTo(2);
        jdbc.update("UPDATE public.member SET temp_password_expires_at=now()+interval '1 hour' WHERE member_id=?",caller);
        var restricted=login(caller,original);String restrictedId=restricted.id();
        jdbc.update("UPDATE public.member SET temp_password_expires_at=now()-interval '1 second' WHERE member_id=?",caller);
        var expired=error(restricted.send("PUT","/members/me/password",input(original,next)),400,"CURRENT_PASSWORD_MISMATCH");assertThat(expired).isEqualTo(mismatch);
        assertThat(restricted.id().equals(restrictedId)).isTrue();assertThat(hash().equals(oldHash)).isTrue();assertThat(sessionCount(caller)).isEqualTo(3);
        jdbc.update("UPDATE public.member SET temp_password_expires_at=NULL WHERE member_id=?",caller);
        assertThat(data(second.get("/auth/me")).path("memberId").asLong()).isEqualTo(caller);
    }
    @Test
    void samePasswordIs400AndKeepsEverySession()throws Exception {
        var another=login(caller,original);String old=browser.id(),oldHash=hash();
        var error=error(browser.send("PUT","/members/me/password",input(original,original)),400,"NEW_PASSWORD_EQUALS_CURRENT");
        assertThat(error.path("message").asText()).isEqualTo("새 비밀번호는 현재 비밀번호와 달라야 합니다.");
        assertThat(browser.id().equals(old)).isTrue();assertThat(hash().equals(oldHash)).isTrue();assertThat(sessionCount(caller)).isEqualTo(2);
        assertThat(data(another.get("/auth/me")).path("memberId").asLong()).isEqualTo(caller);
    }
    @Test
    void whitespaceIsNotTrimmedAndUnicode128CodePointsAreSupported()throws Exception {
        String spaced=" "+UUID.randomUUID()+"Aa1! ";jdbc.update("UPDATE public.member SET password_hash=? WHERE member_id=?",passwords.encode(spaced),caller);
        error(browser.send("PUT","/members/me/password",input(spaced.trim(),next)),400,"CURRENT_PASSWORD_MISMATCH");
        String unicode=" Aa1!"+"😀".repeat(122)+" ";assertThat(unicode.codePointCount(0,unicode.length())).isEqualTo(128);
        data(browser.send("PUT","/members/me/password",input(spaced,unicode)));
        assertThat(passwords.matches(unicode,hash())).isTrue();assertThat(passwords.matches(unicode.trim(),hash())).isFalse();
        assertThat(data(login(caller,unicode).get("/auth/me")).path("memberId").asLong()).isEqualTo(caller);
    }
    @Test
    void passwordWorkRunsWithoutTransactionOrBoundConnection()throws Exception {
        var matches=new AtomicInteger();var encodes=new AtomicInteger();
        doAnswer(inv->{assertNoTransaction();matches.incrementAndGet();return inv.callRealMethod();}).when(passwords).matches(anyString(),anyString());
        doAnswer(inv->{assertNoTransaction();encodes.incrementAndGet();return inv.callRealMethod();}).when(passwords).encode(anyString());
        data(browser.send("PUT","/members/me/password",input(original,next)));assertThat(matches.get()).isEqualTo(2);assertThat(encodes.get()).isEqualTo(1);
    }
    private void assertNoTransaction() {assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isFalse();assertThat(TransactionSynchronizationManager.hasResource(jdbc.getDataSource())).isFalse();}
    @Test
    void hashChangedAfterComparisonIsRecheckedUnderLock()throws Exception {
        String competingHash=passwords.encode(UUID.randomUUID()+"Cc3!");
        doAnswer(inv->{jdbc.update("UPDATE public.member SET password_hash=? WHERE member_id=?",competingHash,caller);return inv.callRealMethod();}).when(passwords).encode(anyString());
        String old=browser.id();error(browser.send("PUT","/members/me/password",input(original,next)),400,"CURRENT_PASSWORD_MISMATCH");
        assertThat(hash().equals(competingHash)).isTrue();assertThat(browser.id().equals(old)).isTrue();
    }
    @Test
    void failureAfterSessionDeletionRollsBackHashExpiryAndSessionRowsBeforeRotation()throws Exception {
        jdbc.update("UPDATE public.member SET temp_password_expires_at=now()+interval '1 hour' WHERE member_id=?",caller);
        var another=login(caller,original);String old=browser.id(),oldHash=hash();
        doAnswer(inv->{inv.callRealMethod();throw new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);}).when(repository).deleteOtherSessions(anyLong(),anyString());
        error(browser.send("PUT","/members/me/password",input(original,next)),500,"INTERNAL_SERVER_ERROR");
        assertThat(hash().equals(oldHash)).isTrue();assertThat(browser.id().equals(old)).isTrue();assertThat(sessionCount(caller)).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT temp_password_expires_at IS NOT NULL FROM public.member WHERE member_id=?",Boolean.class,caller)).isTrue();
        assertThat(data(another.get("/auth/me")).path("mustChangePassword").asBoolean()).isTrue();
    }
    @ParameterizedTest @ValueSource(strings={"short","abcdefgh1","abcdefgh!","12345678!","Ab1!\nxxxx"})
    void invalidNewPasswordIs400AndDoesNotWrite(String invalid)throws Exception {
        String old=browser.id(),oldHash=hash();var e=error(browser.send("PUT","/members/me/password",input(original,invalid)),400,"VALIDATION_ERROR");
        assertThat(e.path("fieldErrors").get(0).path("field").asText()).isEqualTo("newPassword");
        assertThat(hash().equals(oldHash)).isTrue();assertThat(browser.id().equals(old)).isTrue();
    }
    @Test
    void inputBoundsUnknownFieldsCsrfAndInactiveMembersAreRejected()throws Exception {
        var tooLong=input(original,"Aa1!"+"😀".repeat(125));error(browser.send("PUT","/members/me/password",tooLong),400,"VALIDATION_ERROR");
        error(browser.send("PUT","/members/me/password",input("x".repeat(129),next)),400,"VALIDATION_ERROR");
        var unknown=input(original,next);unknown.put("memberId",other);error(browser.send("PUT","/members/me/password",unknown),400,"INVALID_JSON");
        error(browser.send("PUT","/members/me/password",Map.of("newPassword",next)),400,"INVALID_JSON");
        error(browser.withoutCsrf("PUT","/members/me/password",input(original,next)),403,"CSRF_INVALID");
        error(new Browser().send("PUT","/members/me/password",input(original,next)),401,"UNAUTHENTICATED");
        jdbc.update("UPDATE public.member SET withdrawn_at=now() WHERE member_id=?",caller);
        error(browser.send("PUT","/members/me/password",input(original,next)),401,"UNAUTHENTICATED");
    }

    private JsonNode data(HttpResponse<String> r) {assertThat(r.statusCode()).isEqualTo(200);return body(r).path("data");}
    private JsonNode error(HttpResponse<String> r,int status,String code) {assertThat(r.statusCode()).isEqualTo(status);var e=body(r).path("error");assertThat(e.path("code").asText()).isEqualTo(code);return e;}
    private JsonNode body(HttpResponse<String> r) {
        assertThat(r.body().contains(original) || r.body().contains(next)).isFalse();
        assertThat(r.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");var b=json.readTree(r.body());
        String id=r.headers().firstValue("X-Request-Id").orElseThrow();UUID.fromString(id);assertThat(b.path("meta").path("requestId").asText()).isEqualTo(id);return b;
    }
    private void assertCsrfExpired(HttpResponse<String> r) {
        var cookie=r.headers().allValues("Set-Cookie").stream().filter(v->v.startsWith("XSRF-TOKEN=")).map(v->HttpCookie.parse(v).getFirst()).toList().getLast();
        assertThat(cookie.getValue().isEmpty()).isTrue();assertThat(cookie.getMaxAge()).isZero();assertThat(cookie.getPath()).isEqualTo("/");
    }
    private Browser withSession(String id) {
        var b=new Browser();var cookie=new HttpCookie("SESSION",Base64.getEncoder().encodeToString(id.getBytes(StandardCharsets.UTF_8)));cookie.setPath("/api");cookie.setVersion(0);
        b.cookies.getCookieStore().add(URI.create("http://127.0.0.1:"+port),cookie);return b;
    }
    private class Browser {
        private final CookieManager cookies=new CookieManager(null,CookiePolicy.ACCEPT_ALL);
        private final HttpClient http=HttpClient.newBuilder().cookieHandler(cookies).build();
        String id() {String encoded=cookies.getCookieStore().getCookies().stream().filter(c->c.getName().equals("SESSION")).findFirst().orElseThrow().getValue();return new String(Base64.getDecoder().decode(encoded),StandardCharsets.UTF_8);}
        HttpResponse<String> get(String p)throws Exception{return send("GET",p,null);}
        HttpResponse<String> send(String method,String p,Object value)throws Exception {
            var request=request(p);if(!method.equals("GET")) {
                assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);String token=cookies.getCookieStore().getCookies().stream().filter(c->c.getName().equals("XSRF-TOKEN")).findFirst().orElseThrow().getValue();request.header("X-XSRF-TOKEN",token);
            }
            return execute(request,method,value);
        }
        HttpResponse<String> withoutCsrf(String method,String p,Object value)throws Exception{return execute(request(p),method,value);}
        private HttpRequest.Builder request(String p) {return HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api"+p)).timeout(Duration.ofSeconds(15));}
        private HttpResponse<String> execute(HttpRequest.Builder request,String method,Object value)throws Exception {
            if(value!=null)request.header("Content-Type","application/json");
            return http.send(request.method(method,value==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(value))).build(),HttpResponse.BodyHandlers.ofString());
        }
    }
}
