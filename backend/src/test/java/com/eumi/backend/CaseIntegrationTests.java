package com.eumi.backend;

import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import com.eumi.backend.cases.CaseRepository;
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
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** 실제 PostgreSQL·PBKDF2·HTTP. 기관별 합성 데이터만 만들고 지운다. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.DEFINED_PORT,
        properties="server.port=${EUMI_CASE_TEST_PORT:0}")
class CaseIntegrationTests {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired PasswordEncoder passwords;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired JsonMapper json;
    @MockitoSpyBean CaseRepository repository;
    private final String marker = "Case synthetic " + UUID.randomUUID();
    private final Map<Long,String> emails = new HashMap<>();
    private final List<Long> orgs = new ArrayList<>();
    private long org, otherOrg, caller, colleague, unassigned, foreign, withdrawn;
    private String password;
    private Browser browser;

    @BeforeEach
    void setupSyntheticMembers() throws Exception {
        org = organization(); otherOrg = organization();
        password = UUID.randomUUID()+"Aa1!"; String hash = passwords.encode(password);
        caller = member(org, hash); colleague = member(org, hash); unassigned = member(org, hash);
        withdrawn = member(org, hash); foreign = member(otherOrg, hash);
        jdbc.update("UPDATE member SET withdrawn_at=now() WHERE member_id=?", withdrawn);
        browser = login(caller);
    }
    private long organization() {
        long id=jdbc.queryForObject("INSERT INTO organization(org_name,jurisdiction_sigungu_code,official_domain) VALUES (?,'11680','eumi.test') RETURNING org_id",Long.class,marker);
        orgs.add(id); return id;
    }
    private long member(long organization, String hash) {
        String email="case-"+UUID.randomUUID()+"@eumi.test";
        long id=jdbc.queryForObject("INSERT INTO member(org_id,email_normalized,name,password_hash) VALUES (?,?,'Synthetic member',?) RETURNING member_id",Long.class,organization,email,hash);
        emails.put(id,email);return id;
    }
    private Browser login(long member) throws Exception {
        var b=new Browser(); assertThat(b.send("POST","/auth/login",Map.of("email",emails.get(member),"password",password)).statusCode()).isEqualTo(200);return b;
    }
    @AfterEach
    void cleanupOnlyOwnedRows() {
        reset(repository);
        for(long id:orgs)jdbc.update("DELETE FROM case_record WHERE org_id=?",id);
        for(long id:emails.keySet()) {
            sessions.findByPrincipalName(Long.toString(id)).keySet().forEach(sessions::deleteById);
            jdbc.update("DELETE FROM member WHERE member_id=? AND org_id IN (?,?)",id,org,otherOrg);
        }
        for(long id:orgs)jdbc.update("DELETE FROM organization WHERE org_id=? AND org_name=?",id,marker);
    }

    private Map<String,Object> input(String name, List<Long> managers) {
        return new HashMap<>(Map.of("name",name,"birthDate","1980-01-01","gender","남","dongCode","1168066000",
                "firstRegisteredAt","2020-01-01","managerMemberIds",managers));
    }
    private long create(Browser b,String name,List<Long> managers) throws Exception {
        return data(b.send("POST","/cases",input(name,managers)),201).path("caseId").asLong();
    }
    private Map<String,Object> edit(long caseId,String name,List<Long> managers) throws Exception {
        var input=input(name,managers);
        input.put("updatedAt",data(browser.get(path(caseId)),200).path("updatedAt").asText());
        return input;
    }
    private Map<String,Object> consultation(String date) {
        return new HashMap<>(Map.of("consultedAt",date,"purpose"," Synthetic purpose ","category","기타",
                "categoryEtc"," Synthetic other ","content"," Synthetic content "));
    }
    private String path(long caseId) {return "/cases/"+caseId;}
    private String consultations(long id){return path(id)+"/consultations";}

    @Test
    void caseCrudAutoAssignsCallerDeduplicatesManagersAndKeepsNumberAfterChangingYear() throws Exception {
        long id=create(browser," Synthetic case ",List.of(colleague,colleague));
        var d=data(browser.get(path(id)),200);
        assertThat(d.size()).isEqualTo(17);
        assertThat(d.path("name").asText()).isEqualTo("Synthetic case");
        assertThat(d.path("managementNo").asText()).isEqualTo("2020-0001");
        assertThat(d.path("managers").size()).isEqualTo(2);
        assertThat(d.path("managers").get(0).has("title")).isTrue();
        assertThat(d.path("managers").get(0).path("title").isNull()).isTrue();
        assertThat(d.has("lastRecordedAt") && d.path("lastRecordedAt").isNull()).isTrue();
        var edit=edit(id,"Synthetic edited",List.of(caller,colleague)); edit.put("firstRegisteredAt","2021-01-01");
        noContent(browser.send("PUT",path(id),edit));
        d=data(browser.get(path(id)),200);
        assertThat(d.path("managementNo").asText()).isEqualTo("2020-0001");
        assertThat(d.path("firstRegisteredAt").asText()).isEqualTo("2021-01-01");
        noContent(browser.send("DELETE",path(id),null));
        error(browser.get(path(id)),404,"NOT_FOUND");
    }

    @Test
    void sharedManagerCanEditAndRemoveCallerWhoThenLosesAccess() throws Exception {
        long id=create(browser,"Synthetic shared",List.of(colleague));
        noContent(browser.send("PUT",path(id),edit(id,"Synthetic reassigned",List.of(colleague))));
        error(browser.get(path(id)),403,"FORBIDDEN");
        error(browser.send("DELETE",path(id),null),403,"FORBIDDEN");
        assertThat(data(login(colleague).get(path(id)),200).path("managers").size()).isEqualTo(1);
    }

    @Test
    void unassignedAndOtherOrganizationCannotReadOrWriteCasesOrConsultations() throws Exception {
        long id=create(browser,"Synthetic protected",List.of(caller));
        long note=data(browser.send("POST",consultations(id),consultation("2020-01-02")),201).path("consultationId").asLong();
        for(long member:List.of(unassigned,foreign)) {
            Browser denied=login(member);int status=member==foreign?404:403;String code=member==foreign?"NOT_FOUND":"FORBIDDEN";
            error(denied.get(path(id)),status,code);
            error(denied.send("PUT",path(id),edit(id,"Synthetic denied",List.of(member))),status,code);
            error(denied.send("DELETE",path(id),null),status,code);
            error(denied.get(consultations(id)),status,code);
            error(denied.get(consultations(id)+"/"+note),status,code);
            error(denied.send("POST",consultations(id),consultation("2020-01-02")),status,code);
            error(denied.send("PUT",consultations(id)+"/"+note,consultation("2020-01-02")),status,code);
            error(denied.send("DELETE",consultations(id)+"/"+note,null),status,code);
            assertThat(data(denied.get("/cases"),200).path("totalCount").asLong()).isZero();
        }
    }

    @Test
    void foreignCaseRowLockDoesNotBlockUnauthorizedWrites() throws Exception {
        var otherBrowser=login(foreign);
        long id=create(otherBrowser,"Synthetic foreign locked",List.of(foreign));
        long note=data(otherBrowser.send("POST",consultations(id),consultation("2020-01-02")),201)
                .path("consultationId").asLong();
        try(var connection=jdbc.getDataSource().getConnection(); var executor=Executors.newSingleThreadExecutor()) {
            connection.setAutoCommit(false);
            try {
                try(var statement=connection.prepareStatement("SELECT case_id FROM public.case_record WHERE case_id=? AND org_id=? FOR UPDATE")) {
                    statement.setLong(1,id);statement.setLong(2,otherOrg);
                    try(var rows=statement.executeQuery()){assertThat(rows.next()).isTrue();}
                }
                // 이 독립 연결의 행 잠금을 유지한 채 타 기관 쓰기 네 경로가 모두 404로 끝나야 한다.
                var rejected=executor.submit(()->{
                    error(browser.send("DELETE",path(id),null),404,"NOT_FOUND");
                    error(browser.send("POST",consultations(id),consultation("2020-01-02")),404,"NOT_FOUND");
                    error(browser.send("PUT",consultations(id)+"/"+note,consultation("2020-01-02")),404,"NOT_FOUND");
                    error(browser.send("DELETE",consultations(id)+"/"+note,null),404,"NOT_FOUND");
                    return null;
                });
                rejected.get(5,TimeUnit.SECONDS);
            } finally {
                // 수정 전 코드가 잠금 대기해 실패해도 반드시 풀어 서버 요청과 자체 fixture를 정리한다.
                connection.rollback();
            }
        }
    }

    @Test
    void duplicateCheckOnlyRevealsOwnedAssignedCasesAndDoesNotBlockCreation() throws Exception {
        long own=create(browser,"Synthetic duplicate",List.of(caller));
        create(login(unassigned),"Synthetic duplicate",List.of(unassigned));
        create(login(foreign),"Synthetic duplicate",List.of(foreign));
        var request=new HashMap<String,Object>(Map.of("name"," Synthetic duplicate ","birthDate","1980-01-01"));
        var result=data(browser.send("POST","/cases/duplicate-check",request),200).path("duplicates");
        assertThat(result.size()).isEqualTo(1);assertThat(result.get(0).path("caseId").asLong()).isEqualTo(own);
        request.put("excludeCaseId",own);
        assertThat(data(browser.send("POST","/cases/duplicate-check",request),200).path("duplicates").isEmpty()).isTrue();
        create(browser,"Synthetic duplicate",List.of(caller));
    }

    @Test
    void filtersSortingLiteralSearchAndPaginationRespectOnlyOwnCases() throws Exception {
        long noNote=create(browser,"Synthetic %_\\ literal",List.of(caller));
        long withNote=create(browser,"Synthetic second",List.of(caller));
        data(browser.send("POST",consultations(withNote),consultation("2020-03-01")),201);
        create(login(unassigned),"Synthetic hidden",List.of(unassigned));
        var all=data(browser.get("/cases?page=9007199254740991&size=1"),200);
        assertThat(all.path("page").asLong()).isEqualTo(2);assertThat(all.path("totalPages").asLong()).isEqualTo(2);
        for(String direction:List.of("asc","desc")) {
            var items=data(browser.get("/cases?sort=lastRecordedAt&direction="+direction),200).path("items");
            assertThat(items.get(0).path("caseId").asLong()).isEqualTo(withNote);
            assertThat(items.get(1).path("caseId").asLong()).isEqualTo(noNote);
        }
        for(String sort:List.of("name","region","age","gender","firstRegisteredAt","lastRecordedAt"))
            assertThat(data(browser.get("/cases?sort="+sort),200).path("totalCount").asLong()).isEqualTo(2);
        assertThat(data(browser.get("/cases?keyword=%25_%5C"),200).path("items").get(0).path("caseId").asLong()).isEqualTo(noNote);
        var dated=data(browser.get("/cases?sidoCode=11&sigunguCode=11680&dongCode=1168066000&ageGroup=중장년&gender=남&registeredFrom=2020-01-01&registeredTo=2020-01-01&recordedFrom=2020-02-01&recordedTo=2020-04-01"),200);
        assertThat(dated.path("items").size()).isEqualTo(1);
        assertThat(dated.path("items").get(0).path("caseId").asLong()).isEqualTo(withNote);
        var empty=data(browser.get("/cases?keyword=Synthetic-no-match&page=999"),200);
        assertThat(empty.path("page").asLong()).isEqualTo(1);assertThat(empty.path("totalPages").asLong()).isZero();
        assertThat(empty.path("items").isEmpty()).isTrue();
        assertThat(data(browser.get("/cases?keyword=2020-0001"),200).path("totalCount").asLong()).isEqualTo(1);
    }

    @Test
    void consultationCrudPreservesOriginalRecorderSortAndLastRecordedDate() throws Exception {
        long id=create(browser,"Synthetic consultations",List.of(colleague));
        long first=data(browser.send("POST",consultations(id),consultation("2020-02-01")),201).path("consultationId").asLong();
        long latest=data(browser.send("POST",consultations(id),consultation("2020-03-01")),201).path("consultationId").asLong();
        long sameDay=data(browser.send("POST",consultations(id),consultation("2020-03-01")),201).path("consultationId").asLong();
        var list=data(browser.get(consultations(id)),200);
        assertThat(list.size()).isEqualTo(3);assertThat(list.get(0).path("consultationId").asLong()).isEqualTo(sameDay);
        assertThat(list.get(1).path("consultationId").asLong()).isEqualTo(latest);
        assertThat(list.get(0).size()).isEqualTo(6);
        var edit=consultation("2020-01-01");edit.put("category","정기상담");edit.put("categoryEtc","ignored");
        noContent(login(colleague).send("PUT",consultations(id)+"/"+sameDay,edit));
        var detail=data(browser.get(consultations(id)+"/"+sameDay),200);
        assertThat(detail.size()).isEqualTo(8);assertThat(detail.path("recorderMemberId").asLong()).isEqualTo(caller);
        assertThat(detail.path("categoryEtc").isNull()).isTrue();assertThat(detail.path("purpose").asText()).isEqualTo("Synthetic purpose");
        assertThat(detail.path("content").asText()).isEqualTo("Synthetic content");
        noContent(browser.send("DELETE",consultations(id)+"/"+latest,null));
        assertThat(data(browser.get(path(id)),200).path("lastRecordedAt").asText()).isEqualTo("2020-02-01");
        noContent(browser.send("DELETE",consultations(id)+"/"+first,null));
        noContent(browser.send("DELETE",consultations(id)+"/"+sameDay,null));
        assertThat(data(browser.get(path(id)),200).path("lastRecordedAt").isNull()).isTrue();
    }

    @Test
    void consultationMustBelongToPathAndCaseDeletionCascades() throws Exception {
        long id=create(browser,"Synthetic one",List.of(caller));long other=create(browser,"Synthetic two",List.of(caller));
        long note=data(browser.send("POST",consultations(id),consultation("2020-01-01")),201).path("consultationId").asLong();
        error(browser.get(consultations(other)+"/"+note),404,"NOT_FOUND");
        error(browser.send("PUT",consultations(other)+"/"+note,consultation("2020-01-01")),404,"NOT_FOUND");
        error(browser.send("DELETE",consultations(other)+"/"+note,null),404,"NOT_FOUND");
        noContent(browser.send("DELETE",path(id),null));
        assertThat(jdbc.queryForObject("SELECT count(*) FROM consultation WHERE consultation_id=?",Long.class,note)).isZero();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM case_manager WHERE case_id=?",Long.class,id)).isZero();
    }

    @Test
    void invalidManagersReturn400WithoutChangingTheCase() throws Exception {
        for(long manager:List.of(foreign,withdrawn))error(browser.send("POST","/cases",input("Synthetic invalid",List.of(manager))),400,"VALIDATION_ERROR");
        long id=create(browser,"Synthetic original",List.of(caller));
        for(long manager:List.of(foreign,withdrawn)) {
            error(browser.send("PUT",path(id),edit(id,"Synthetic changed",List.of(manager))),400,"VALIDATION_ERROR");
        }
        assertThat(data(browser.get(path(id)),200).path("name").asText()).isEqualTo("Synthetic original");
    }

    @Test
    void numberIsPerOrganizationAndYearAndHighestDeletedNumberCanBeReused() throws Exception {
        long one=create(browser,"Synthetic one",List.of(caller));long two=create(browser,"Synthetic two",List.of(caller));
        assertThat(data(browser.get(path(one)),200).path("managementNo").asText()).isEqualTo("2020-0001");
        assertThat(data(browser.get(path(two)),200).path("managementNo").asText()).isEqualTo("2020-0002");
        noContent(browser.send("DELETE",path(two),null));
        long reused=create(browser,"Synthetic reused",List.of(caller));
        assertThat(data(browser.get(path(reused)),200).path("managementNo").asText()).isEqualTo("2020-0002");
        var year=input("Synthetic year",List.of(caller));year.put("firstRegisteredAt","2021-01-01");
        assertThat(data(browser.send("POST","/cases",year),201).path("managementNo").asText()).isEqualTo("2021-0001");
        var outside=login(foreign);
        assertThat(data(outside.send("POST","/cases",input("Synthetic foreign",List.of(foreign))),201).path("managementNo").asText()).isEqualTo("2020-0001");
    }

    @Test
    void number9999IsRejectedWithoutCallingBrokenOverflowFunctionOrInserting() throws Exception {
        jdbc.update("INSERT INTO case_record(org_id,management_no,name,birth_date,gender,dong_code,first_registered_at) "
                +"VALUES (?,'2020-9999','Synthetic maximum','1980-01-01','남','1168066000','2020-01-01')",org);
        error(browser.send("POST","/cases",input("Synthetic exhausted",List.of(caller))),409,"MANAGEMENT_NUMBER_EXHAUSTED");
        var order=inOrder(repository);
        order.verify(repository).lockOrganization(org);
        order.verify(repository).lastNumber(org,"2020");
        verify(repository,never()).nextNumber(anyLong(),any());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM case_record WHERE org_id=?",Long.class,org)).isEqualTo(1);
    }

    @Test
    void failureAfterCaseInsertRollsBackTheCaseAndNumberCanBeIssuedAgain() throws Exception {
        doThrow(new IllegalStateException("Synthetic write fault")).when(repository).replaceManagers(anyLong(),anyCollection());
        error(browser.send("POST","/cases",input("Synthetic rollback",List.of(caller))),500,"INTERNAL_SERVER_ERROR");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM case_record WHERE org_id=?",Long.class,org)).isZero();
        reset(repository);
        assertThat(data(browser.send("POST","/cases",input("Synthetic retry",List.of(caller))),201).path("managementNo").asText()).isEqualTo("2020-0001");
    }

    @Test
    void concurrentRegistrationsIssueDistinctNumbersUnderTheOrganizationLock() throws Exception {
        var browsers=new ArrayList<Browser>();for(int i=0;i<4;i++)browsers.add(login(caller));
        try(var executor=Executors.newFixedThreadPool(4)) {
            var futures=new ArrayList<Future<String>>();
            for(var b:browsers)futures.add(executor.submit(()->data(b.send("POST","/cases",input("Synthetic concurrent",List.of(caller))),201).path("managementNo").asText()));
            var numbers=new HashSet<String>();for(var future:futures)numbers.add(future.get(15,TimeUnit.SECONDS));
            assertThat(numbers).containsExactlyInAnyOrder("2020-0001","2020-0002","2020-0003","2020-0004");
        }
    }

    @Test
    void unauthenticatedTemporaryAndWithdrawnSessionsCannotAccessCases() throws Exception {
        long id=create(browser,"Synthetic protected",List.of(caller));
        var paths=List.of("/cases",path(id),consultations(id));
        for(String p:paths)error(new Browser().get(p),401,"UNAUTHENTICATED");
        jdbc.update("UPDATE member SET temp_password_expires_at=now()+interval '1 hour' WHERE member_id=?",caller);
        for(String p:paths)error(browser.get(p),403,"PASSWORD_CHANGE_REQUIRED");
        Browser restricted=login(caller);
        error(restricted.send("POST","/cases",input("Synthetic denied",List.of(caller))),403,"PASSWORD_CHANGE_REQUIRED");
        jdbc.update("UPDATE member SET withdrawn_at=now() WHERE member_id=?",caller);
        for(String p:paths)error(browser.get(p),401,"UNAUTHENTICATED");
    }

    @Test
    void inputValidationAndCsrfDoNotStoreRejectedData() throws Exception {
        var input=input("Synthetic future",List.of(caller));input.put("birthDate",LocalDate.now(ZoneId.of("Asia/Seoul")).plusDays(1).toString());
        error(browser.send("POST","/cases",input),400,"VALIDATION_ERROR");
        input=input("Synthetic none",List.of());error(browser.send("POST","/cases",input),400,"VALIDATION_ERROR");
        input=input("Synthetic unknown",List.of(caller));input.put("orgId",otherOrg);error(browser.send("POST","/cases",input),400,"INVALID_JSON");
        input=input("Synthetic region",List.of(caller));input.put("dongCode","9999999999");error(browser.send("POST","/cases",input),400,"VALIDATION_ERROR");
        error(browser.withoutCsrf("POST","/cases",input("Synthetic csrf",List.of(caller))),403,"CSRF_INVALID");
        long id=create(browser,"Synthetic note validation",List.of(caller));
        var note=consultation("2020-01-01");note.put("categoryEtc"," ");error(browser.send("POST",consultations(id),note),400,"VALIDATION_ERROR");
        note=consultation(LocalDate.now(ZoneId.of("Asia/Seoul")).plusDays(1).toString());error(browser.send("POST",consultations(id),note),400,"VALIDATION_ERROR");
    }

    @Test void detailKeepsSixFractionDigitsAndAnOffsetAndRegistrationDoesNotRequireAVersion() throws Exception {
        long id=create(browser,"Synthetic precise version",List.of(caller));
        var time=OffsetDateTime.parse("2026-11-10T21:03:05.120300+09:00");
        jdbc.update("UPDATE public.case_record SET updated_at=? WHERE case_id=?",time,id);
        var value=data(browser.get(path(id)),200).path("updatedAt").asText();
        assertThat(value).isEqualTo("2026-11-10T21:03:05.120300+09:00");
        assertThat(OffsetDateTime.parse(value).toInstant()).isEqualTo(time.toInstant());
    }
    @Test void aStaleVersionReturns409WithoutChangingTheCaseOrManagers() throws Exception {
        long id=create(browser,"Synthetic before version",List.of(caller,colleague));
        var first=edit(id,"Synthetic first saved",List.of(caller,colleague));
        String old=(String)first.get("updatedAt");noContent(browser.send("PUT",path(id),first));
        var saved=data(browser.get(path(id)),200);assertThat(saved.path("updatedAt").asText()).isNotEqualTo(old);
        var stale=input("Synthetic stale overwrite",List.of(colleague));stale.put("updatedAt",old);
        error(browser.send("PUT",path(id),stale),409,"STATE_CONFLICT");
        assertThat(data(browser.get(path(id)),200)).isEqualTo(saved);
    }
    @Test void changingOnlyManagersAlsoChangesTheVersion() throws Exception {
        long id=create(browser,"Synthetic managers version",List.of(caller));
        var edit=edit(id,"Synthetic managers version",List.of(caller,colleague));String old=(String)edit.get("updatedAt");
        noContent(browser.send("PUT",path(id),edit));
        var saved=data(browser.get(path(id)),200);assertThat(saved.path("updatedAt").asText()).isNotEqualTo(old);
        assertThat(saved.path("managers").size()).isEqualTo(2);
        error(browser.send("PUT",path(id),edit),409,"STATE_CONFLICT");
        assertThat(data(browser.get(path(id)),200)).isEqualTo(saved);
    }
    @ParameterizedTest @ValueSource(strings={"missing","null","","not-a-timestamp","2026-11-10T21:03:05.120300","2026-02-30T21:03:05+09:00"})
    void invalidUpdateVersionsHaveAFieldValidationError(String value) throws Exception {
        long id=create(browser,"Synthetic invalid version",List.of(caller));
        var before=data(browser.get(path(id)),200);var edit=input("Synthetic rejected version",List.of(caller));
        if(!value.equals("missing")) edit.put("updatedAt",value.equals("null") ? null : value);
        var response=browser.send("PUT",path(id),edit);error(response,400,"VALIDATION_ERROR");
        assertThat(body(response).path("error").path("fieldErrors").valueStream().map(f->f.path("field").asText()).toList()).contains("updatedAt");
        assertThat(data(browser.get(path(id)),200)).isEqualTo(before);
    }
    @Test void equivalentOffsetsAndSubMicrosecondDigitsCompareAsTheSameInstant() throws Exception {
        long id=create(browser,"Synthetic equivalent offset",List.of(caller));
        var edit=edit(id,"Synthetic UTC version",List.of(caller));
        var expected=OffsetDateTime.parse((String)edit.get("updatedAt")).toInstant();
        edit.put("updatedAt",expected.atOffset(ZoneOffset.UTC).toString());noContent(browser.send("PUT",path(id),edit));
        edit=edit(id,"Synthetic microsecond version",List.of(caller));
        expected=OffsetDateTime.parse((String)edit.get("updatedAt")).toInstant();
        edit.put("updatedAt",expected.plusNanos(999).atOffset(ZoneOffset.UTC).toString());
        noContent(browser.send("PUT",path(id),edit));
    }
    @Test void concurrentUpdatesWithTheSameVersionHaveExactlyOneWinner() throws Exception {
        long id=create(browser,"Synthetic concurrent version",List.of(caller,colleague));var coworker=login(colleague);
        String version=data(browser.get(path(id)),200).path("updatedAt").asText();
        var first=input("Synthetic concurrent first",List.of(caller,colleague));first.put("updatedAt",version);
        var second=input("Synthetic concurrent second",List.of(caller,colleague));second.put("updatedAt",version);
        var ready=new CountDownLatch(2);var release=new CountDownLatch(1);
        doAnswer(call->{ready.countDown();if(!release.await(5,TimeUnit.SECONDS)) throw new IllegalStateException("Synthetic update gate timeout");return call.callRealMethod();})
                .when(repository).lockOrganization(org);
        try(var executor=Executors.newFixedThreadPool(2)) {
            var one=executor.submit(()->browser.send("PUT",path(id),first));
            var two=executor.submit(()->coworker.send("PUT",path(id),second));
            try {assertThat(ready.await(5,TimeUnit.SECONDS)).isTrue();}
            finally {release.countDown();}
            var a=one.get(12,TimeUnit.SECONDS);var b=two.get(12,TimeUnit.SECONDS);
            assertThat(List.of(a.statusCode(),b.statusCode())).containsExactlyInAnyOrder(204,409);
            noContent(a.statusCode()==204 ? a : b);error(a.statusCode()==409 ? a : b,409,"STATE_CONFLICT");
            assertThat(data(browser.get(path(id)),200).path("name").asText()).isEqualTo(a.statusCode()==204 ? first.get("name") : second.get("name"));
        }
    }
    @Test void permissionAndDeletedCaseChecksPrecedeAStaleVersionConflict() throws Exception {
        long id=create(browser,"Synthetic access before conflict",List.of(caller));
        var edit=edit(id,"Synthetic current save",List.of(caller));noContent(browser.send("PUT",path(id),edit));
        error(login(unassigned).send("PUT",path(id),edit),403,"FORBIDDEN");
        error(login(foreign).send("PUT",path(id),edit),404,"NOT_FOUND");
        noContent(browser.send("DELETE",path(id),null));
        error(browser.send("PUT",path(id),edit),404,"NOT_FOUND");
    }
    @Test void withdrawalAssignmentChangesInvalidateAnAlreadyOpenedCaseForm() throws Exception {
        long id=create(browser,"Synthetic withdrawal version",List.of(caller,colleague));var coworker=login(colleague);
        var edit=input("Synthetic stale after withdrawal",List.of(colleague));
        String old=data(coworker.get(path(id)),200).path("updatedAt").asText();edit.put("updatedAt",old);
        noContent(browser.send("POST","/members/me/withdrawal",Map.of("password",password,"transfers",List.of(),"resourceTransfers",List.of())));
        var current=data(coworker.get(path(id)),200);assertThat(current.path("updatedAt").asText()).isNotEqualTo(old);
        error(coworker.send("PUT",path(id),edit),409,"STATE_CONFLICT");
        assertThat(data(coworker.get(path(id)),200)).isEqualTo(current);
    }

    @ParameterizedTest
    @ValueSource(strings={"/cases?size=0","/cases?size=101","/cases?page=0","/cases?sort=unknown","/cases?direction=unknown",
            "/cases?sidoCode=1","/cases?sigunguCode=1168","/cases?dongCode=11680660","/cases?gender=unknown",
            "/cases?ageGroup=unknown","/cases?registeredFrom=2020-03-01&registeredTo=2020-01-01",
            "/cases?recordedFrom=2020-03-01&recordedTo=2020-01-01","/cases/0","/cases/9007199254740992"})
    void malformedSearchOrIdsAre400(String p)throws Exception {error(browser.get(p),400,"VALIDATION_ERROR");}

    private JsonNode data(HttpResponse<String> response,int status) {
        assertThat(response.statusCode()).isEqualTo(status);var body=body(response);assertThat(body.path("success").asBoolean()).isTrue();return body.path("data");
    }
    private void error(HttpResponse<String> response,int status,String code) {
        assertThat(response.statusCode()).isEqualTo(status);var body=body(response);assertThat(body.path("error").path("code").asText()).isEqualTo(code);
        assertThat(response.body()).doesNotContain("Synthetic protected","Synthetic denied");
    }
    private JsonNode body(HttpResponse<String> response) {
        assertThat(response.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");
        var body=json.readTree(response.body());String id=response.headers().firstValue("X-Request-Id").orElseThrow();UUID.fromString(id);
        assertThat(body.path("meta").path("requestId").asText()).isEqualTo(id);return body;
    }
    private void noContent(HttpResponse<String> response) {
        assertThat(response.statusCode()).isEqualTo(204);assertThat(response.body()).isEmpty();
        assertThat(response.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");
    }
    private class Browser {
        private final CookieManager cookies=new CookieManager(null,CookiePolicy.ACCEPT_ALL);
        private final HttpClient http=HttpClient.newBuilder().cookieHandler(cookies).build();
        HttpResponse<String> get(String p)throws Exception{return send("GET",p,null);}
        HttpResponse<String> send(String method,String p,Object content)throws Exception {
            var request=request(p);
            if(!method.equals("GET")) {
                assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
                String token=cookies.getCookieStore().getCookies().stream().filter(c->c.getName().equals("XSRF-TOKEN")).findFirst().orElseThrow().getValue();
                request.header("X-XSRF-TOKEN",token);
            }
            return execute(request,method,content);
        }
        HttpResponse<String> withoutCsrf(String method,String p,Object content)throws Exception{return execute(request(p),method,content);}
        private HttpRequest.Builder request(String p)throws Exception {
            return HttpRequest.newBuilder(new URI("http://127.0.0.1:"+port+"/api"+p)).timeout(Duration.ofSeconds(10));
        }
        private HttpResponse<String> execute(HttpRequest.Builder request,String method,Object content)throws Exception {
            if(content!=null)request.header("Content-Type","application/json");
            return http.send(request.method(method,content==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(content))).build(),HttpResponse.BodyHandlers.ofString());
        }
    }
}
