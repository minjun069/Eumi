package com.eumi.backend;

import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.*;
import com.eumi.backend.agent.*;
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
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties="eumi.ai.fake-step-delay=30s")
class ConversationHistoryIntegrationTests {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired PasswordEncoder passwords;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired JsonMapper json;
    @Autowired AgentMessageWriter writer;
    @MockitoSpyBean AgentClient client;
    private final String marker="history-"+UUID.randomUUID().toString().substring(0,12);
    private final Map<Long,String> emails=new HashMap<>();
    private long org,caller,other;
    private String password;
    private Browser browser;

    @BeforeEach
    void setup()throws Exception {
        org=jdbc.queryForObject("INSERT INTO public.organization(org_name,jurisdiction_sigungu_code,official_domain) VALUES (?,'11680','eumi.test') RETURNING org_id",Long.class,marker);
        password=UUID.randomUUID()+"Aa1!";String hash=passwords.encode(password);caller=member(hash);other=member(hash);browser=login(caller);
    }
    private long member(String hash) {
        String email="history-"+UUID.randomUUID()+"@eumi.test";
        long id=jdbc.queryForObject("INSERT INTO public.member(org_id,email_normalized,name,password_hash) VALUES (?,?,?,?) RETURNING member_id",Long.class,org,email,marker+" member",hash);emails.put(id,email);return id;
    }
    private Browser login(long member)throws Exception {
        var b=new Browser();assertThat(b.send("POST","/auth/login",Map.of("email",emails.get(member),"password",password)).statusCode()).isEqualTo(200);return b;
    }
    @AfterEach
    void cleanupOnlyOwnedFixtures() {
        // 취소 실패를 주입한 경우에도 실제 Fake의 자체 타이머를 해제한 뒤 자체 대화만 지운다.
        reset(client);
        for(long member:emails.keySet()) {
            for(UUID id:jdbc.queryForList("SELECT conversation_id FROM public.ai_conversation WHERE member_id=?",UUID.class,member))client.cancel(id);
            jdbc.update("DELETE FROM public.ai_conversation WHERE member_id=?",member);
            sessions.findByPrincipalName(Long.toString(member)).keySet().forEach(sessions::deleteById);
            jdbc.update("DELETE FROM public.member WHERE member_id=? AND org_id=? AND name=?",member,org,marker+" member");
        }
        if(org!=0)jdbc.update("DELETE FROM public.organization WHERE org_id=? AND org_name=?",org,marker);
    }
    private String path(UUID id) {return "/members/me/conversations/"+id;}
    private UUID conversation(long member) {
        var id=UUID.randomUUID();jdbc.update("INSERT INTO public.ai_conversation(conversation_id,member_id) VALUES (?,?)",id,member);return id;
    }
    private long question(UUID id,String content) {
        return jdbc.queryForObject("INSERT INTO public.ai_message(conversation_id,role,status,content) VALUES (?,'Member','질문',?) RETURNING message_id",Long.class,id,content);
    }
    private void ai(UUID id,long question,String status,String artifacts) {
        jdbc.update("INSERT INTO public.ai_message(conversation_id,question_id,role,status,content,details,artifacts) VALUES (?,?,'AI',?,'Synthetic AI content','Synthetic details',?::jsonb)",id,question,status,artifacts);
    }
    private UUID completed(long member,String title,String status) {
        UUID id=conversation(member);long q=question(id,title);ai(id,q,status,null);return id;
    }
    private void metadata(UUID id,int ageDays,int keepDays) {
        jdbc.update("UPDATE public.ai_conversation SET last_message_at=TIMESTAMPTZ '2026-01-01 00:00:00+09'+(? * interval '1 day'),delete_scheduled_at=current_date+? WHERE conversation_id=?",ageDays,keepDays,id);
    }
    private List<UUID> ids(JsonNode page) {var ids=new ArrayList<UUID>();page.path("items").forEach(i->ids.add(UUID.fromString(i.path("conversationId").asText())));return ids;}
    private long count(String table,UUID id) {return jdbc.queryForObject("SELECT count(*) FROM public."+table+" WHERE conversation_id=?",Long.class,id);}

    @Test
    void listUsesOwnerRetentionPaginationAndDeterministicTieOrder()throws Exception {
        UUID a=completed(caller,"Synthetic first","완료"),b=completed(caller,"Synthetic second","실패"),old=completed(caller,"Synthetic older","취소");
        metadata(a,2,1);metadata(b,2,1);metadata(old,1,1);
        UUID expired=completed(caller,"Synthetic expired","완료");metadata(expired,10,0);
        completed(other,"Synthetic foreign","완료");
        var ties=new ArrayList<>(List.of(a,b));ties.sort(Comparator.comparing(UUID::toString));
        var p=data(browser.get("/members/me/conversations?size=2&page=1"));
        assertThat(p.size()).isEqualTo(5);assertThat(p.path("totalCount").asLong()).isEqualTo(3);assertThat(p.path("totalPages").asLong()).isEqualTo(2);
        assertThat(ids(p)).containsExactlyElementsOf(ties);assertThat(p.path("items").get(0).size()).isEqualTo(5);
        p=data(browser.get("/members/me/conversations?size=2&page=9007199254740991"));
        assertThat(p.path("page").asLong()).isEqualTo(2);assertThat(ids(p)).containsExactly(old);
        assertThat(ids(data(login(other).get("/members/me/conversations")))).hasSize(1);
    }
    @Test
    void emptyListReturnsPageOneAndZeroTotalPages()throws Exception {
        var p=data(browser.get("/members/me/conversations?page=8"));assertThat(p.path("totalCount").asLong()).isZero();
        assertThat(p.path("page").asLong()).isEqualTo(1);assertThat(p.path("totalPages").asLong()).isZero();assertThat(ids(p)).isEmpty();
    }
    @Test
    void detailReusesAllAgentMessagesAndCountsFailedAndCancelledQuestions()throws Exception {
        UUID id=conversation(caller);long first=question(id,"이름: [이름]; Synthetic stored question");
        ai(id,first,"진행",null);ai(id,first,"완료","{\"synthetic\":[1,2]}");
        long second=question(id,"Synthetic failed question");ai(id,second,"실패",null);
        long third=question(id,"Synthetic cancelled question");ai(id,third,"취소",null);
        var detail=data(browser.get(path(id)));assertThat(detail.size()).isEqualTo(5);
        assertThat(detail.path("firstQuestion").asText()).isEqualTo("이름: [이름]; Synthetic stored question");
        var messages=detail.path("messages");assertThat(messages.size()).isEqualTo(7);
        var oldApi=data(browser.get("/agent/conversations/"+id+"/messages?after=0"));assertThat(messages).isEqualTo(oldApi.path("messages"));
        long previous=0;for(var m:messages){assertThat(m.size()).isEqualTo(8);assertThat(m.path("messageId").asLong()).isGreaterThan(previous);previous=m.path("messageId").asLong();}
        assertThat(messages.get(0).has("questionId") && messages.get(0).path("questionId").isNull()).isTrue();
        assertThat(messages.get(2).path("artifacts").path("synthetic").size()).isEqualTo(2);
        assertThat(data(browser.get("/members/me/conversations")).path("items").get(0).path("questionCount").asLong()).isEqualTo(3);
        verify(client,never()).start(eq(id),anyLong());verify(client,never()).status(id);
    }
    @Test
    void foreignMissingAndExpiredConversationsAre404AndNeverCancelled()throws Exception {
        UUID foreign=completed(other,"Synthetic protected","완료"),missing=UUID.randomUUID(),expired=completed(caller,"Synthetic expired","완료");metadata(expired,0,0);
        for(UUID id:List.of(foreign,missing,expired)) {
            error(browser.get(path(id)),404,"NOT_FOUND");error(browser.send("DELETE",path(id),null),404,"NOT_FOUND");verify(client,never()).cancel(id);
        }
        assertThat(count("ai_conversation",foreign)).isEqualTo(1);assertThat(count("ai_message",foreign)).isEqualTo(2);
    }
    @Test
    void deletingCompletedConversationCascadesAndRejectsLateRows()throws Exception {
        UUID id=completed(caller,"Synthetic completed","완료");long q=jdbc.queryForObject("SELECT message_id FROM public.ai_message WHERE conversation_id=? AND status='질문'",Long.class,id);
        noContent(browser.send("DELETE",path(id),null));verify(client,never()).cancel(id);
        assertThat(count("ai_conversation",id)).isZero();assertThat(count("ai_message",id)).isZero();
        assertThat(writer.append(id,q,"진행","Synthetic late",null)).isFalse();
        error(browser.get(path(id)),404,"NOT_FOUND");error(browser.send("DELETE",path(id),null),404,"NOT_FOUND");
        assertThat(data(browser.get("/members/me/conversations")).path("totalCount").asLong()).isZero();
    }
    @Test
    void deletingActualRunningFakeCancelsOutsideTransactionBeforePhysicalDelete()throws Exception {
        var request=new HashMap<String,Object>();request.put("conversationId",null);request.put("question","Synthetic running question");
        var accepted=browser.send("POST","/agent/questions",request);assertThat(accepted.statusCode()).isEqualTo(202);
        var created=body(accepted).path("data");UUID id=UUID.fromString(created.path("conversationId").asText());long q=created.path("questionId").asLong();
        assertThat(client.status(id).running()).isTrue();
        doAnswer(invocation->{
            assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
            assertThat(TransactionSynchronizationManager.hasResource(jdbc.getDataSource())).isFalse();
            assertThat(count("ai_conversation",id)).isEqualTo(1);
            return invocation.callRealMethod();
        }).when(client).cancel(id);
        noContent(browser.send("DELETE",path(id),null));verify(client,times(1)).cancel(id);
        assertThat(client.status(id).running()).isFalse();assertThat(count("ai_conversation",id)).isZero();assertThat(count("ai_message",id)).isZero();
        assertThat(writer.append(id,q,"완료","Synthetic late answer",null)).isFalse();
    }
    @Test
    void cancelUnavailableStillUsesExistingFallbackThenDeletes()throws Exception {
        UUID id=conversation(caller);long q=question(id,"Synthetic stalled question");
        doThrow(new AgentClient.Unavailable()).when(client).cancel(id);
        noContent(browser.send("DELETE",path(id),null));verify(client).cancel(id);
        assertThat(count("ai_conversation",id)).isZero();assertThat(count("ai_message",id)).isZero();
        assertThat(writer.append(id,q,"취소",null,null)).isFalse();
    }
    @Test
    void readingPendingHistoryDoesNotRestartOrRecoverAi()throws Exception {
        UUID id=conversation(caller);question(id,"Synthetic pending question");
        jdbc.update("UPDATE public.ai_message SET created_at=now()-interval '1 hour' WHERE conversation_id=?",id);
        assertThat(data(browser.get(path(id))).path("messages").size()).isEqualTo(1);
        verify(client,never()).start(eq(id),anyLong());verify(client,never()).status(id);verify(client,never()).cancel(id);
    }
    @ParameterizedTest @ValueSource(strings={"page=0","page=9007199254740992","page=abc","size=0","size=101","size=abc"})
    void invalidPaginationIs400(String query)throws Exception {error(browser.get("/members/me/conversations?"+query),400,"VALIDATION_ERROR");}
    @Test
    void malformedUuidIs400ForDetailAndDelete()throws Exception {
        error(browser.get("/members/me/conversations/not-a-uuid"),400,"VALIDATION_ERROR");error(browser.send("DELETE","/members/me/conversations/not-a-uuid",null),400,"VALIDATION_ERROR");
    }
    @Test
    void authenticationRestrictionAndCsrfProtectHistory()throws Exception {
        UUID id=completed(caller,"Synthetic protected","완료");
        var anonymous=new Browser();for(String p:List.of("/members/me/conversations",path(id)))error(anonymous.get(p),401,"UNAUTHENTICATED");
        error(anonymous.send("DELETE",path(id),null),401,"UNAUTHENTICATED");
        error(browser.withoutCsrf("DELETE",path(id)),403,"CSRF_INVALID");
        jdbc.update("UPDATE public.member SET temp_password_expires_at=now()+interval '1 hour' WHERE member_id=?",caller);var restricted=login(caller);
        for(var b:List.of(browser,restricted)) {
            for(String p:List.of("/members/me/conversations",path(id)))error(b.get(p),403,"PASSWORD_CHANGE_REQUIRED");
            error(b.send("DELETE",path(id),null),403,"PASSWORD_CHANGE_REQUIRED");
        }
        jdbc.update("UPDATE public.member SET withdrawn_at=now() WHERE member_id=?",caller);
        error(browser.get("/members/me/conversations"),401,"UNAUTHENTICATED");error(browser.get(path(id)),401,"UNAUTHENTICATED");error(browser.send("DELETE",path(id),null),401,"UNAUTHENTICATED");
        assertThat(count("ai_conversation",id)).isEqualTo(1);
    }

    private JsonNode data(HttpResponse<String> r) {assertThat(r.statusCode()).isEqualTo(200);return body(r).path("data");}
    private void error(HttpResponse<String> r,int status,String code) {assertThat(r.statusCode()).isEqualTo(status);assertThat(body(r).path("error").path("code").asText()).isEqualTo(code);}
    private JsonNode body(HttpResponse<String> r) {
        assertThat(r.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");var b=json.readTree(r.body());
        String id=r.headers().firstValue("X-Request-Id").orElseThrow();UUID.fromString(id);assertThat(b.path("meta").path("requestId").asText()).isEqualTo(id);return b;
    }
    private void noContent(HttpResponse<String> r) {assertThat(r.statusCode()).isEqualTo(204);assertThat(r.body()).isEmpty();assertThat(r.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");UUID.fromString(r.headers().firstValue("X-Request-Id").orElseThrow());}
    private class Browser {
        private final CookieManager cookies=new CookieManager(null,CookiePolicy.ACCEPT_ALL);
        private final HttpClient http=HttpClient.newBuilder().cookieHandler(cookies).build();
        HttpResponse<String> get(String p)throws Exception {return send("GET",p,null);}
        HttpResponse<String> send(String method,String p,Object content)throws Exception {
            var request=request(p);if(!method.equals("GET")) {
                assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
                String token=cookies.getCookieStore().getCookies().stream().filter(c->c.getName().equals("XSRF-TOKEN")).findFirst().orElseThrow().getValue();request.header("X-XSRF-TOKEN",token);
            }
            return execute(request,method,content);
        }
        HttpResponse<String> withoutCsrf(String method,String p)throws Exception {return execute(request(p),method,null);}
        private HttpRequest.Builder request(String p) {return HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api"+p)).timeout(Duration.ofSeconds(10));}
        private HttpResponse<String> execute(HttpRequest.Builder request,String method,Object content)throws Exception {
            if(content!=null)request.header("Content-Type","application/json");
            return http.send(request.method(method,content==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(content))).build(),HttpResponse.BodyHandlers.ofString());
        }
    }
}
