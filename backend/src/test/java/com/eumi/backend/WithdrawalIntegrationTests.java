package com.eumi.backend;

import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import com.eumi.backend.agent.*;
import com.eumi.backend.auth.password.PasswordChangeRepository;
import com.eumi.backend.cases.CaseRepository;
import com.eumi.backend.mypage.WithdrawalRepository;
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
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** 실제 PostgreSQL·HTTP·세션·fake AI. 단독 8080 확인은 EUMI_WITHDRAWAL_TEST_PORT=8080으로 실행한다. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.DEFINED_PORT,
        properties={"server.port=${EUMI_WITHDRAWAL_TEST_PORT:0}","eumi.ai.mode=fake","eumi.ai.fake-step-delay=30s"})
class WithdrawalIntegrationTests {
    private static final String PATH="/members/me/withdrawal";
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired JsonMapper json;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired AgentMessageWriter writer;
    @Autowired FakeAgentClient fake;
    @MockitoSpyBean WithdrawalRepository repository;
    @MockitoSpyBean PasswordChangeRepository accounts;
    @MockitoSpyBean PasswordEncoder passwords;
    @MockitoSpyBean AgentLifecycle lifecycle;
    @MockitoSpyBean AgentRepository agent;
    @MockitoSpyBean CaseRepository cases;
    private final String marker="withdraw-"+UUID.randomUUID();
    private final Map<Long,String> emails=new LinkedHashMap<>();
    private final List<Long> orgs=new ArrayList<>();
    private final List<UUID> conversations=new ArrayList<>();
    private long org,otherOrg,caller,colleague,withdrawn,foreign;
    private String password;
    private Browser browser;

    @BeforeEach void setup() throws Exception {
        org=organization(); otherOrg=organization();password=UUID.randomUUID()+"Aa2!";String hash=passwords.encode(password);
        caller=member(org,hash,"B");colleague=member(org,hash,"A");withdrawn=member(org,hash,"C");foreign=member(otherOrg,hash,"D");
        jdbc.update("UPDATE public.member SET withdrawn_at=now() WHERE member_id=?",withdrawn);
        browser=login(caller);
    }
    private long organization() {
        long id=jdbc.queryForObject("INSERT INTO public.organization(org_name,jurisdiction_sigungu_code,official_domain) VALUES (?,'11680','eumi.test') RETURNING org_id",Long.class,marker);
        orgs.add(id);return id;
    }
    private long member(long organization,String hash,String name) {
        String email="withdraw-"+UUID.randomUUID()+"@eumi.test";
        long id=jdbc.queryForObject("INSERT INTO public.member(org_id,email_normalized,name,password_hash) VALUES (?,?,?,?) RETURNING member_id",Long.class,organization,email,name,hash);
        emails.put(id,email);return id;
    }
    private Browser login(long member) throws Exception {
        var b=new Browser();assertThat(b.post("/auth/login",Map.of("email",emails.get(member),"password",password)).statusCode()).isEqualTo(200);return b;
    }
    @AfterEach void cleanup() {
        reset(repository,accounts,passwords,lifecycle,agent,cases);
        for(UUID id:conversations) lifecycle.cancel(id);
        for(long id:orgs) jdbc.update("DELETE FROM public.case_record WHERE org_id=?",id);
        for(long id:emails.keySet()) {
            jdbc.update("DELETE FROM public.welfare_resource WHERE manager_member_id=?",id);
            jdbc.update("DELETE FROM public.ai_conversation WHERE member_id=?",id);
            sessions.findByPrincipalName(Long.toString(id)).keySet().forEach(sessions::deleteById);
        }
        for(long id:emails.keySet()) jdbc.update("DELETE FROM public.member WHERE member_id=? AND org_id IN (?,?)",id,org,otherOrg);
        for(long id:orgs) jdbc.update("DELETE FROM public.organization WHERE org_id=? AND org_name=?",id,marker);
    }
    private long caseRow(long... managers) {
        long id=jdbc.queryForObject("INSERT INTO public.case_record(org_id,management_no,name,birth_date,gender,dong_code,first_registered_at) "
                + "VALUES (?,public.next_management_no(?,DATE '2020-01-01'),?,DATE '1980-01-01','남','1168066000',DATE '2020-01-01') RETURNING case_id",Long.class,org,org,marker);
        for(long manager:managers) jdbc.update("INSERT INTO public.case_manager(case_id,member_id) VALUES (?,?)",id,manager);
        return id;
    }
    private long resource(long manager,String status,int endDays,boolean deleted) {
        return jdbc.queryForObject("""
                INSERT INTO public.welfare_resource(resource_name,operating_org_name,target,support_age_groups,support_gender,
                sigungu_code,period_start,period_end,fee,manual_status,manager_member_id,capacity,deleted_at)
                VALUES (?,'Synthetic org','Synthetic target',ARRAY['무관'],'무관','11680',current_date-20,current_date+?,0,?,?,5,
                CASE WHEN ? THEN now() ELSE NULL END) RETURNING resource_id
                """,Long.class,"Synthetic resource",endDays,status,manager,deleted);
    }
    private UUID conversation(long member,int days) {
        UUID id=UUID.randomUUID();conversations.add(id);
        jdbc.update("INSERT INTO public.ai_conversation(conversation_id,member_id) VALUES (?,?)",id,member);
        jdbc.update("UPDATE public.ai_conversation SET delete_scheduled_at=current_date+? WHERE conversation_id=?",days,id);
        return id;
    }
    private Map<String,Object> input(List<Map<String,Object>> transfers,List<Map<String,Object>> resources) {
        return new HashMap<>(Map.of("password",password,"transfers",transfers,"resourceTransfers",resources));
    }
    private Map<String,Object> emptyInput() {return input(List.of(),List.of());}
    private Map<String,Object> transfer(long id,long successor) {return Map.of("caseId",id,"newManagerMemberId",successor);}
    private Map<String,Object> resourceTransfer(long id,long successor) {return Map.of("resourceId",id,"newManagerMemberId",successor);}
    private long count(String sql,Object... args) {return jdbc.queryForObject(sql,Long.class,args);}
    private long sessionCount(long member) {return count("SELECT count(*) FROM public.spring_session WHERE principal_name=?",Long.toString(member));}
    private boolean isWithdrawn() {return jdbc.queryForObject("SELECT withdrawn_at IS NOT NULL FROM public.member WHERE member_id=?",Boolean.class,caller);}
    // DB 스냅샷은 해시·세션값·개인정보를 포함하지 않고 합성 데이터의 관련 상태만 비교한다.
    private String state() {
        return jdbc.queryForList("SELECT member_id,withdrawn_at,updated_at FROM public.member WHERE org_id IN (?,?) ORDER BY member_id",org,otherOrg).toString()
                +jdbc.queryForList("SELECT cm.case_id,cm.member_id FROM public.case_manager cm JOIN public.case_record c ON c.case_id=cm.case_id WHERE c.org_id=? ORDER BY 1,2",org)
                +jdbc.queryForList("SELECT resource_id,manager_member_id,updated_at FROM public.welfare_resource WHERE manager_member_id IN (SELECT member_id FROM public.member WHERE org_id IN (?,?)) ORDER BY resource_id",org,otherOrg)
                +jdbc.queryForList("SELECT conversation_id FROM public.ai_conversation WHERE member_id=? ORDER BY conversation_id",caller)
                +jdbc.queryForList("SELECT message_id,status FROM public.ai_message WHERE conversation_id IN (SELECT conversation_id FROM public.ai_conversation WHERE member_id=?) ORDER BY message_id",caller)
                +sessionCount(caller);
    }
    private void unchanged(String before) {assertThat(state().equals(before)).as("owned business rows and session count unchanged").isTrue();}

    @Test void infoSeparatesActiveCoManagersResourcesSuccessorsAndUnexpiredOwnedConversations() throws Exception {
        String storedHash=accounts.account(caller,false).orElseThrow().hash();
        long tiedSuccessor=member(org,storedHash,"A"),lastSuccessor=member(org,storedHash,"Z");
        long sole=caseRow(caller),inactiveOther=caseRow(caller,withdrawn),shared=caseRow(caller,colleague);caseRow(colleague);
        jdbc.update("INSERT INTO public.consultation(case_id,consulted_at,purpose,category,content,recorder_member_id) VALUES (?,current_date,'Synthetic','초기상담','Synthetic',?)",sole,caller);
        long ongoing=resource(caller,"진행 중",3,false);
        long nextOngoing=resource(caller,"진행 중",2,false);
        resource(caller,"진행 중",-1,false);resource(caller,"종료",20,false);resource(caller,"진행 중",3,true);resource(colleague,"진행 중",3,false);
        conversation(caller,1);conversation(caller,0);conversation(caller,-1);conversation(colleague,1);
        var info=data(browser.get(PATH),200);assertThat(info.size()).isEqualTo(7);
        assertThat(ids(info.path("soleCases"),"caseId")).containsExactly(sole,inactiveOther).doesNotContain(shared);
        var first=info.path("soleCases").get(0);assertThat(first.size()).isEqualTo(6);
        assertThat(first.path("managementNo").asText()).isEqualTo("2020-0001");assertThat(first.path("ageGroup").asText()).isEqualTo("중장년");
        assertThat(first.path("dongName").asText()).isNotBlank();assertThat(first.path("lastRecordedAt").isString()).isTrue();
        assertThat(info.path("soleCases").get(1).path("lastRecordedAt").isNull()).isTrue();
        assertThat(info.path("sharedCaseCount").asLong()).isEqualTo(1);
        assertThat(ids(info.path("successors"),"memberId")).containsExactly(colleague,tiedSuccessor,lastSuccessor);
        assertThat(info.path("successors").get(0).has("title") && info.path("successors").get(0).path("title").isNull()).isTrue();
        assertThat(ids(info.path("ongoingResources"),"resourceId")).containsExactly(ongoing,nextOngoing);
        assertThat(info.path("ongoingResources").get(0).path("periodEnd").isString()).isTrue();
        assertThat(info.path("endedResourceCount").asLong()).isEqualTo(2);assertThat(info.path("resourceCount").asLong()).isEqualTo(4);
        assertThat(info.path("conversationCount").asLong()).isEqualTo(1);
        verify(lifecycle,never()).cancel(any());
    }
    @Test void transfersSoftDeletePreserveHistoricalReferencesAndPermanentlyRemoveAllSessionsAndConversations() throws Exception {
        long sole=caseRow(caller),shared=caseRow(caller,colleague),ongoing=resource(caller,"진행 중",5,false);
        long ended=resource(caller,"종료",5,false),autoEnded=resource(caller,"진행 중",-1,false);
        long record=jdbc.queryForObject("INSERT INTO public.consultation(case_id,consulted_at,purpose,category,content,recorder_member_id) VALUES (?,current_date,'Synthetic','초기상담','Synthetic',?) RETURNING consultation_id",Long.class,sole,caller);
        UUID conversation=conversation(caller,1);long question=agent.insertQuestion(conversation,"Synthetic question");
        writer.append(conversation,question,"완료","Synthetic answer",null);
        var second=login(caller);var survivor=login(colleague);long colleagueSessions=sessionCount(colleague);
        var response=browser.post(PATH,input(List.of(transfer(sole,colleague)),List.of(resourceTransfer(ongoing,colleague))));noContent(response);
        assertThat(response.headers().allValues("Set-Cookie").stream().anyMatch(v->v.startsWith("SESSION=") && v.contains("Max-Age=0"))).isTrue();
        assertThat(isWithdrawn()).isTrue();assertThat(count("SELECT count(*) FROM public.case_manager WHERE member_id=?",caller)).isZero();
        for(long id:List.of(sole,shared)) assertThat(count("SELECT count(*) FROM public.case_manager WHERE case_id=? AND member_id=?",id,colleague)).isEqualTo(1);
        assertThat(count("SELECT manager_member_id FROM public.welfare_resource WHERE resource_id=?",ongoing)).isEqualTo(colleague);
        for(long id:List.of(ended,autoEnded)) {
            assertThat(count("SELECT manager_member_id FROM public.welfare_resource WHERE resource_id=?",id)).isEqualTo(caller);
            assertThat(jdbc.queryForObject("SELECT manager_name='퇴사자' AND manager_title IS NULL AND manager_withdrawn AND status='종료' FROM public.v_resource_summary WHERE resource_id=?",Boolean.class,id)).isTrue();
            assertThat(data(survivor.get("/resources/"+id),200).path("manager").path("name").asText()).isEqualTo("퇴사자");
        }
        assertThat(count("SELECT recorder_member_id FROM public.consultation WHERE consultation_id=?",record)).isEqualTo(caller);
        assertThat(count("SELECT count(*) FROM public.ai_conversation WHERE member_id=?",caller)).isZero();
        assertThat(count("SELECT count(*) FROM public.ai_message WHERE conversation_id=?",conversation)).isZero();
        assertThat(sessionCount(caller)).isZero();assertThat(sessionCount(colleague)).isEqualTo(colleagueSessions);
        error(browser.get("/auth/me"),401,"UNAUTHENTICATED");error(second.get("/auth/me"),401,"UNAUTHENTICATED");
        error(new Browser().post("/auth/login",Map.of("email",emails.get(caller),"password",password)),401,"INVALID_CREDENTIALS");
        assertThat(sessionCount(caller)).isZero();
    }
    @Test void emptyTargetsAllowWithdrawalWithNoActiveSuccessors() throws Exception {
        jdbc.update("UPDATE public.member SET withdrawn_at=now() WHERE member_id=?",colleague);
        assertThat(data(browser.get(PATH),200).path("successors").isEmpty()).isTrue();
        noContent(browser.post(PATH,emptyInput()));assertThat(isWithdrawn()).isTrue();assertThat(sessionCount(caller)).isZero();
    }
    @Test void wrongPasswordDoesNotChangeAnythingOrCancelAi() throws Exception {
        var input=emptyInput();input.put("password",UUID.randomUUID().toString());String before=state();
        error(browser.post(PATH,input),400,"WITHDRAW_PASSWORD_MISMATCH");unchanged(before);verify(lifecycle,never()).cancel(any());
    }
    @ParameterizedTest @ValueSource(strings={"missingCase","extraCase","resource","withdrawnSuccessor","foreignSuccessor","missingSuccessor"})
    void conflictingTargetSetsOrIneligibleSuccessorsRollBack(String scenario) throws Exception {
        long sole=caseRow(caller),ongoing=resource(caller,"진행 중",5,false);
        List<Map<String,Object>> transfers=List.of(transfer(sole,colleague)),resources=List.of(resourceTransfer(ongoing,colleague));
        switch(scenario) {
            case "missingCase" -> transfers=List.of();
            case "extraCase" -> transfers=List.of(transfer(sole,colleague),transfer(caseRow(colleague),colleague));
            case "resource" -> resources=List.of();
            case "withdrawnSuccessor" -> {
                data(browser.get(PATH),200);jdbc.update("UPDATE public.member SET withdrawn_at=now() WHERE member_id=?",colleague);
            }
            case "foreignSuccessor" -> transfers=List.of(transfer(sole,foreign));
            case "missingSuccessor" -> transfers=List.of(transfer(sole,9007199254740991L));
        }
        String before=state();error(browser.post(PATH,input(transfers,resources)),409,"STATE_CONFLICT");unchanged(before);
    }
    @Test void changedAssignmentsAfterInfoRequireARefresh() throws Exception {
        long id=caseRow(caller);assertThat(data(browser.get(PATH),200).path("soleCases").size()).isEqualTo(1);
        jdbc.update("INSERT INTO public.case_manager(case_id,member_id) VALUES (?,?)",id,colleague);
        String before=state();error(browser.post(PATH,input(List.of(transfer(id,colleague)),List.of())),409,"STATE_CONFLICT");unchanged(before);
    }
    @Test void failureAfterAllBusinessWritesRollsEverythingBack() throws Exception {
        long sole=caseRow(caller),ongoing=resource(caller,"진행 중",5,false);UUID id=conversation(caller,1);agent.insertQuestion(id,"Synthetic question");
        writer.append(id,count("SELECT message_id FROM public.ai_message WHERE conversation_id=? AND status='질문'",id),"완료","Synthetic",null);
        doAnswer(call->{call.callRealMethod();throw new IllegalStateException("Synthetic rollback probe");}).when(accounts).deleteAllSessions(caller);
        String before=state();error(browser.post(PATH,input(List.of(transfer(sole,colleague)),List.of(resourceTransfer(ongoing,colleague)))),500,"INTERNAL_SERVER_ERROR");
        unchanged(before);assertThat(sessionCount(caller)).isEqualTo(1);assertThat(isWithdrawn()).isFalse();
    }
    @Test void duplicateSelfInvalidJsonCsrfAndRestrictedSessionsAreRejected() throws Exception {
        long id=caseRow(caller);String before=state();var duplicate=transfer(id,colleague);
        var response=error(browser.post(PATH,input(List.of(duplicate,duplicate),List.of())),400,"VALIDATION_ERROR");
        assertThat(response.path("fieldErrors").get(0).path("field").asText()).isEqualTo("transfers");
        response=error(browser.post(PATH,input(List.of(transfer(id,caller)),List.of())),400,"VALIDATION_ERROR");
        assertThat(response.path("fieldErrors").get(0).path("field").asText()).isEqualTo("transfers");
        var bad=emptyInput();bad.put("extra",true);error(browser.post(PATH,bad),400,"INVALID_JSON");
        error(browser.withoutCsrf(PATH,emptyInput()),403,"CSRF_INVALID");unchanged(before);
        error(new Browser().get(PATH),401,"UNAUTHENTICATED");
        jdbc.update("UPDATE public.member SET temp_password_expires_at=now()+interval '1 hour' WHERE member_id=?",caller);
        for(var b:List.of(browser,login(caller))) {
            error(b.get(PATH),403,"PASSWORD_CHANGE_REQUIRED");error(b.post(PATH,emptyInput()),403,"PASSWORD_CHANGE_REQUIRED");
        }
        assertThat(isWithdrawn()).isFalse();
    }
    @Test void hashingAndCancellationAreOutsideTransactionsAndBusinessLocksUseTheSharedOrder() throws Exception {
        var tx=new AtomicBoolean();var connection=new AtomicBoolean();
        doAnswer(call->{tx.set(TransactionSynchronizationManager.isActualTransactionActive());connection.set(TransactionSynchronizationManager.hasResource(jdbc.getDataSource()));return call.callRealMethod();})
                .when(passwords).matches(anyString(),anyString());
        long sole=caseRow(caller),ongoing=resource(caller,"진행 중",5,false);
        var created=data(browser.post("/agent/questions",new AgentDtos.QuestionRequest(null,"Synthetic question")),202);
        UUID id=UUID.fromString(created.path("conversationId").asText());conversations.add(id);
        var cancelTx=new AtomicBoolean();var cancelConnection=new AtomicBoolean();
        doAnswer(call->{cancelTx.set(TransactionSynchronizationManager.isActualTransactionActive());cancelConnection.set(TransactionSynchronizationManager.hasResource(jdbc.getDataSource()));return call.callRealMethod();}).when(lifecycle).cancel(id);
        clearInvocations(repository);
        noContent(browser.post(PATH,input(List.of(transfer(sole,colleague)),List.of(resourceTransfer(ongoing,colleague)))));
        assertThat(tx.get() || connection.get() || cancelTx.get() || cancelConnection.get()).isFalse();
        var order=inOrder(repository);order.verify(repository).lockOrganization(org);order.verify(repository).lockMembers(new TreeSet<>(List.of(caller,colleague)));
        order.verify(repository).lockCases(caller);order.verify(repository).lockResources(caller);
        assertThat(fake.isRunning(id)).isFalse();assertThat(writer.append(id,created.path("questionId").asLong(),"완료","Synthetic late",null)).isFalse();
        assertThatThrownBy(()->agent.insertAi(id,created.path("questionId").asLong(),"완료","Synthetic direct late",null))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(count("SELECT count(*) FROM public.ai_message WHERE conversation_id=?",id)).isZero();
    }
    @Test void passwordChangeBetweenVerificationAndTheLockIsRejected() throws Exception {
        doAnswer(call->{jdbc.update("UPDATE public.member SET password_hash=? WHERE member_id=?",passwords.encode(UUID.randomUUID().toString()),caller);return call.callRealMethod();})
                .when(repository).activeConversations(caller);
        error(browser.post(PATH,emptyInput()),400,"WITHDRAW_PASSWORD_MISMATCH");assertThat(isWithdrawn()).isFalse();assertThat(sessionCount(caller)).isEqualTo(1);
    }
    @ParameterizedTest @ValueSource(strings={"sharedFirst","withdrawalFirst","soleFirst"})
    void concurrentCaseAssignmentAndWithdrawalSerializeOnTheOrganization(String scenario) throws Exception {
        boolean caseFirst=!scenario.equals("withdrawalFirst");
        long id=caseRow(colleague);var coworker=login(colleague);
        var atLocks=new CountDownLatch(2);var firstGate=new CountDownLatch(1);var secondGate=new CountDownLatch(1);
        var firstLocked=new CountDownLatch(1);var finishFirst=new CountDownLatch(1);
        var firstPid=new AtomicInteger();var secondPid=new AtomicInteger();
        org.mockito.stubbing.Answer<Object> first=call->{
            atLocks.countDown();await(firstGate);firstPid.set(jdbc.queryForObject("SELECT pg_backend_pid()",Integer.class));
            Object result=call.callRealMethod();firstLocked.countDown();await(finishFirst);return result;
        };
        org.mockito.stubbing.Answer<Object> second=call->{
            atLocks.countDown();await(secondGate);secondPid.set(jdbc.queryForObject("SELECT pg_backend_pid()",Integer.class));return call.callRealMethod();
        };
        doAnswer(caseFirst ? first : second).when(cases).lockOrganization(org);
        doAnswer(caseFirst ? second : first).when(repository).lockOrganization(org);
        Map<String,Object> edit=Map.of("name","Synthetic edited","birthDate","1980-01-01","gender","남","dongCode","1168066000",
                "firstRegisteredAt","2020-01-01","managerMemberIds",scenario.equals("soleFirst") ? List.of(caller) : List.of(caller,colleague));
        try(var executor=Executors.newFixedThreadPool(2)) {
            var update=executor.submit(()->coworker.execute("PUT","/cases/"+id,edit,coworker.csrf()));
            var withdrawal=executor.submit(()->browser.post(PATH,emptyInput()));
            try {
                assertThat(atLocks.await(8,TimeUnit.SECONDS)).isTrue();firstGate.countDown();assertThat(firstLocked.await(5,TimeUnit.SECONDS)).isTrue();
                secondGate.countDown();assertThat(awaitBlockedSelect(secondPid,firstPid)).as("second request waits for the first organization lock").isTrue();
            } finally {firstGate.countDown();secondGate.countDown();finishFirst.countDown();}
            var withdrawnResponse=withdrawal.get(12,TimeUnit.SECONDS);var updateResponse=update.get(12,TimeUnit.SECONDS);
            if(scenario.equals("soleFirst")) {noContent(updateResponse);error(withdrawnResponse,409,"STATE_CONFLICT");assertThat(isWithdrawn()).isFalse();}
            else if(caseFirst) {noContent(updateResponse);noContent(withdrawnResponse);assertThat(isWithdrawn()).isTrue();}
            else {noContent(withdrawnResponse);error(updateResponse,400,"VALIDATION_ERROR");assertThat(isWithdrawn()).isTrue();}
        }
        assertThat(count("SELECT count(*) FROM public.case_manager cm JOIN public.member m ON m.member_id=cm.member_id WHERE m.org_id=? AND m.withdrawn_at IS NOT NULL",org)).isZero();
        assertThat(count("SELECT count(*) FROM public.case_record c WHERE c.org_id=? AND NOT EXISTS (SELECT 1 FROM public.case_manager cm JOIN public.member m ON m.member_id=cm.member_id WHERE cm.case_id=c.case_id AND m.withdrawn_at IS NULL)",org)).isZero();
    }
    @Test void twoWithdrawalsThatPassedPasswordVerificationHaveOnlyOneSuccess() throws Exception {
        var secondBrowser=login(caller);var entered=new CountDownLatch(2);var release=new CountDownLatch(1);
        doAnswer(call->{entered.countDown();await(release);return call.callRealMethod();}).when(repository).lockOrganization(org);
        try(var executor=Executors.newFixedThreadPool(2)) {
            var first=executor.submit(()->browser.post(PATH,emptyInput()));var second=executor.submit(()->secondBrowser.post(PATH,emptyInput()));
            try {assertThat(entered.await(8,TimeUnit.SECONDS)).isTrue();} finally {release.countDown();}
            var responses=List.of(first.get(12,TimeUnit.SECONDS),second.get(12,TimeUnit.SECONDS));
            assertThat(responses.stream().map(HttpResponse::statusCode).toList()).containsExactlyInAnyOrder(204,404);
            for(var response:responses) {if(response.statusCode()==204) noContent(response);else error(response,404,"NOT_FOUND");}
        }
        assertThat(isWithdrawn()).isTrue();assertThat(sessionCount(caller)).isZero();
    }
    @Test void questionAuthenticatedBeforeWithdrawalCanStillCommitAfterwardsAndIsReportedAsExistingRace() throws Exception {
        var reached=new CountDownLatch(1);var resume=new CountDownLatch(1);
        doAnswer(call->{reached.countDown();await(resume);return call.callRealMethod();}).when(agent).createConversation(any(UUID.class),eq(caller));
        try(var executor=Executors.newSingleThreadExecutor()) {
            var pending=executor.submit(()->browser.post("/agent/questions",new AgentDtos.QuestionRequest(null,"Synthetic race question")));
            try {assertThat(reached.await(8,TimeUnit.SECONDS)).isTrue();noContent(login(caller).post(PATH,emptyInput()));}
            finally {resume.countDown();}
            var created=data(pending.get(12,TimeUnit.SECONDS),202);UUID id=UUID.fromString(created.path("conversationId").asText());conversations.add(id);
            // 기존 AgentService의 인증/신규 대화 INSERT 사이 경합이다. 지시대로 재현·보고만 하고 다른 API는 바꾸지 않는다.
            assertThat(isWithdrawn()).isTrue();assertThat(count("SELECT count(*) FROM public.ai_conversation WHERE member_id=?",caller)).isEqualTo(1);
            assertThat(count("SELECT count(*) FROM public.ai_message WHERE conversation_id=?",id)).isEqualTo(1);
            assertThat(writer.append(id,created.path("questionId").asLong(),"완료","Synthetic late answer",null)).isFalse();
        }
    }
    private static void await(CountDownLatch latch) throws InterruptedException {
        if(!latch.await(10,TimeUnit.SECONDS)) throw new IllegalStateException("Synthetic concurrency gate timed out");
    }
    private boolean awaitBlockedSelect(AtomicInteger requestPid,AtomicInteger blockerPid) throws InterruptedException {
        long deadline=System.nanoTime()+Duration.ofSeconds(4).toNanos();
        do {
            if(requestPid.get()!=0 && Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=? "
                    +"AND wait_event_type='Lock' AND upper(query) LIKE '%FOR UPDATE%' AND ?=ANY(pg_blocking_pids(pid)))",Boolean.class,requestPid.get(),blockerPid.get()))) return true;
            Thread.sleep(10);
        } while(System.nanoTime()<deadline);
        return false;
    }
    private List<Long> ids(JsonNode rows,String key) {var values=new ArrayList<Long>();for(var row:rows) values.add(row.path(key).asLong());return values;}
    private JsonNode data(HttpResponse<String> response,int status) {
        assertThat(response.statusCode()).isEqualTo(status);checkHeaders(response);return json.readTree(response.body()).path("data");
    }
    private JsonNode error(HttpResponse<String> response,int status,String code) {
        assertThat(response.statusCode()).isEqualTo(status);checkHeaders(response);var error=json.readTree(response.body()).path("error");
        assertThat(error.path("code").asText()).isEqualTo(code);return error;
    }
    private void noContent(HttpResponse<String> response) {assertThat(response.statusCode()).isEqualTo(204);assertThat(response.body()).isEmpty();checkHeaders(response);}
    private void checkHeaders(HttpResponse<String> response) {
        assertThat(response.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");UUID.fromString(response.headers().firstValue("X-Request-Id").orElseThrow());
    }
    private class Browser {
        private final CookieManager cookies=new CookieManager(null,CookiePolicy.ACCEPT_ALL);
        private final HttpClient http=HttpClient.newBuilder().cookieHandler(cookies).build();
        HttpResponse<String> get(String path) throws Exception {return execute("GET",path,null,null);}
        HttpResponse<String> post(String path,Object body) throws Exception {return execute("POST",path,body,csrf());}
        String csrf() throws Exception {
            assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
            return cookies.getCookieStore().getCookies().stream().filter(c->c.getName().equals("XSRF-TOKEN")).findFirst().orElseThrow().getValue();
        }
        HttpResponse<String> withoutCsrf(String path,Object body) throws Exception {return execute("POST",path,body,null);}
        HttpResponse<String> execute(String method,String path,Object body,String token) throws Exception {
            var request=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api"+path)).timeout(Duration.ofSeconds(15));
            if(body!=null) request.header("Content-Type","application/json");if(token!=null) request.header("X-XSRF-TOKEN",token);
            return http.send(request.method(method,body==null ? HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body))).build(),HttpResponse.BodyHandlers.ofString());
        }
    }
}
