package com.eumi.backend;

import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.util.stream.Stream;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.*;
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

/** 실제 PostgreSQL·A1 로그인·PBKDF2·HTTP. 생성한 합성 데이터와 세션만 정리한다. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT)
class ResourceIntegrationTests {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired PasswordEncoder passwords;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired JsonMapper json;
    private final String marker="wr-"+UUID.randomUUID().toString().substring(0,12);
    private final Map<Long,String> emails=new HashMap<>();
    private final List<Long> orgs=new ArrayList<>();
    private long caller,colleague,foreign,withdrawn;
    private String password;
    private Browser browser;
    private final LocalDate today=LocalDate.now(ZoneId.of("Asia/Seoul"));

    @BeforeEach
    void setup() throws Exception {
        long org=organization(),other=organization();password=UUID.randomUUID()+"Aa1!";
        String hash=passwords.encode(password);
        caller=member(org,hash);colleague=member(org,hash);foreign=member(other,hash);withdrawn=member(org,hash);
        jdbc.update("UPDATE public.member SET withdrawn_at=now() WHERE member_id=?",withdrawn);
        browser=login(caller);
    }
    private long organization() {
        long id=jdbc.queryForObject("INSERT INTO public.organization(org_name,jurisdiction_sigungu_code,official_domain) VALUES (?,'11680','eumi.test') RETURNING org_id",Long.class,marker);
        orgs.add(id);return id;
    }
    private long member(long org,String hash) {
        String email="wr-"+UUID.randomUUID()+"@eumi.test";
        long id=jdbc.queryForObject("INSERT INTO public.member(org_id,email_normalized,name,password_hash) VALUES (?,?,?,?) RETURNING member_id",Long.class,org,email,marker+" member",hash);
        emails.put(id,email);return id;
    }
    private Browser login(long member)throws Exception {
        var b=new Browser();assertThat(b.send("POST","/auth/login",Map.of("email",emails.get(member),"password",password)).statusCode()).isEqualTo(200);return b;
    }
    @AfterEach
    void cleanupOnlyOwnedRows() {
        for(long member:emails.keySet())jdbc.update("DELETE FROM public.welfare_resource WHERE manager_member_id=?",member);
        for(long member:emails.keySet()) {
            sessions.findByPrincipalName(Long.toString(member)).keySet().forEach(sessions::deleteById);
            jdbc.update("DELETE FROM public.member WHERE member_id=? AND name=?",member,marker+" member");
        }
        for(long org:orgs)jdbc.update("DELETE FROM public.organization WHERE org_id=? AND org_name=?",org,marker);
    }
    private Map<String,Object> input(String suffix,long manager) {
        var i=new HashMap<String,Object>();
        i.put("resourceName",marker+suffix);i.put("operatingOrgName"," Synthetic operating org ");i.put("target"," Synthetic target ");
        i.put("supportAgeGroups",List.of("무관"));i.put("supportGender","무관");i.put("sigunguCode","11680");
        i.put("periodStart",today.toString());i.put("periodEnd",today.plusDays(30).toString());
        i.put("fee",0);i.put("status","진행 중");i.put("managerMemberId",manager);i.put("capacity",10);return i;
    }
    private long create(Map<String,Object> i)throws Exception { return data(browser.send("POST","/resources",i),201).path("resourceId").asLong(); }
    private String path(long id) {return "/resources/"+id;}
    private String search(String extra) {return "/resources?resourceName="+encode(marker)+extra;}
    private static String encode(String s) {return URLEncoder.encode(s,java.nio.charset.StandardCharsets.UTF_8);}
    private List<Long> ids(JsonNode page) {var ids=new ArrayList<Long>();page.path("items").forEach(i->ids.add(i.path("resourceId").asLong()));return ids;}

    @Test
    void crudNormalizesInputKeepsNullsAndSoftDeletes()throws Exception {
        var i=input(" normal",caller);i.put("resourceName"," "+marker+" normal ");i.put("dongCode","1168066000");
        i.put("supportAgeGroups",List.of(" 청년 ","청년","노년"));i.put("actualParticipants",20);
        i.put("supportContent"," Synthetic content ");i.put("applyMethod","  ");
        long id=create(i);var d=data(browser.get(path(id)),200);
        assertThat(d.size()).isEqualTo(24);assertThat(d.path("manager").size()).isEqualTo(5);
        assertThat(d.path("resourceName").asText()).isEqualTo(marker+" normal");
        assertThat(d.path("operatingOrgName").asText()).isEqualTo("Synthetic operating org");
        assertThat(d.path("supportAgeGroups").toString()).isEqualTo("[\"청년\",\"노년\"]");
        assertThat(d.path("actualParticipants").asInt()).isEqualTo(20);
        assertThat(d.path("supportContent").asText()).isEqualTo("Synthetic content");
        assertThat(d.has("applyMethod") && d.path("applyMethod").isNull()).isTrue();
        assertThat(d.path("manager").has("title") && d.path("manager").path("title").isNull()).isTrue();
        assertThat(d.path("editable").asBoolean()).isTrue();assertThat(d.path("manualStatus").asText()).isEqualTo("진행 중");
        var list=data(browser.get(search("")),200);assertThat(list.path("items").get(0).size()).isEqualTo(11);
        jdbc.update("UPDATE public.welfare_resource SET updated_at=TIMESTAMPTZ '2000-01-01 00:00:00+09' WHERE resource_id=?",id);
        noContent(browser.send("PUT",path(id),input(" updated",caller)));
        d=data(browser.get(path(id)),200);
        for(String nullable:List.of("dongCode","dongName","actualParticipants","supportContent","applyMethod"))assertThat(d.has(nullable) && d.path(nullable).isNull()).isTrue();
        assertThat(jdbc.queryForObject("SELECT updated_at>created_at-interval '1 second' FROM public.welfare_resource WHERE resource_id=?",Boolean.class,id)).isTrue();
        var updated=jdbc.queryForObject("SELECT updated_at FROM public.welfare_resource WHERE resource_id=?",OffsetDateTime.class,id);
        noContent(browser.send("DELETE",path(id),null));
        assertThat(jdbc.queryForObject("SELECT deleted_at IS NOT NULL AND updated_at=? FROM public.welfare_resource WHERE resource_id=?",Boolean.class,updated,id)).isTrue();
        error(browser.get(path(id)),404,"NOT_FOUND");error(browser.send("PUT",path(id),input(" gone",caller)),404,"NOT_FOUND");
        error(browser.send("DELETE",path(id),null),404,"NOT_FOUND");
        assertThat(ids(data(browser.get(search("")),200))).doesNotContain(id);
    }

    @Test
    void allInstitutionsReadButOnlyManagerWritesAndTransferChangesAuthority()throws Exception {
        long id=create(input(" protected",caller));
        for(long member:List.of(colleague,foreign)) {
            var other=login(member);assertThat(data(other.get(path(id)),200).path("editable").asBoolean()).isFalse();
            assertThat(ids(data(other.get(search("")),200))).contains(id);
            error(other.send("PUT",path(id),input(" denied",member)),403,"FORBIDDEN");
            error(other.send("DELETE",path(id),null),403,"FORBIDDEN");
        }
        noContent(browser.send("PUT",path(id),input(" transferred",colleague)));
        assertThat(data(browser.get(path(id)),200).path("editable").asBoolean()).isFalse();
        error(browser.send("PUT",path(id),input(" denied",caller)),403,"FORBIDDEN");error(browser.send("DELETE",path(id),null),403,"FORBIDDEN");
        var successor=login(colleague);assertThat(data(successor.get(path(id)),200).path("editable").asBoolean()).isTrue();
        noContent(successor.send("DELETE",path(id),null));
    }

    @Test
    void creatorMayAssignActiveColleagueWithoutGainingWriteAuthority()throws Exception {
        long id=create(input(" delegated",colleague));
        assertThat(data(browser.get(path(id)),200).path("manager").path("memberId").asLong()).isEqualTo(colleague);
        error(browser.send("DELETE",path(id),null),403,"FORBIDDEN");
        noContent(login(colleague).send("PUT",path(id),input(" accepted",colleague)));
    }

    @Test
    void invalidManagersAreFieldErrorsAndLeaveExistingManagerUnchanged()throws Exception {
        long id=create(input(" valid",caller));
        for(long invalid:List.of(foreign,withdrawn,9007199254740991L)) {
            var i=input(" invalid manager",invalid);
            fieldError(browser.send("POST","/resources",i),"managerMemberId");fieldError(browser.send("PUT",path(id),i),"managerMemberId");
        }
        assertThat(data(browser.get(path(id)),200).path("manager").path("memberId").asLong()).isEqualTo(caller);
    }

    static Stream<Arguments> invalidInput() {
        return Stream.of(
                Arguments.of("sigunguCode","99999"),Arguments.of("dongCode","1168099999"),Arguments.of("dongCode","5111052000"),
                Arguments.of("periodEnd","2000-01-01"),Arguments.of("supportAgeGroups",List.of()),
                Arguments.of("supportAgeGroups",List.of("무관","청년")),Arguments.of("supportAgeGroups",List.of("기타")),
                Arguments.of("supportAgeGroups",Arrays.asList("청년",null)),Arguments.of("resourceName","   "),
                Arguments.of("resourceName","가".repeat(51)),Arguments.of("operatingOrgName","가".repeat(51)),
                Arguments.of("target","가".repeat(101)),Arguments.of("supportContent","가".repeat(1001)),Arguments.of("applyMethod","가".repeat(201)),
                Arguments.of("supportGender","전체"),Arguments.of("status","준비"),Arguments.of("fee",-1),Arguments.of("fee",2147483648L),
                Arguments.of("capacity",0),Arguments.of("capacity",2147483648L),Arguments.of("actualParticipants",-1),Arguments.of("actualParticipants",2147483648L));
    }
    @ParameterizedTest(name="invalid {0} #{index}") @MethodSource("invalidInput")
    void invalidValuesAre400WithFieldNamesBeforeDatabaseChecks(String field,Object value)throws Exception {
        var i=input(" rejected",caller);i.put(field,value);fieldError(browser.send("POST","/resources",i),field);
        assertThat(ids(data(browser.get(search("")),200))).isEmpty();
    }

    @Test
    void dongAgeGenderAndCapacityFiltersIncludeUnrestrictedResources()throws Exception {
        long whole=create(input(" whole",caller));
        var i=input(" matching",caller);i.put("dongCode","1168066000");i.put("supportAgeGroups",List.of("노년"));i.put("supportGender","여");long matching=create(i);
        i=input(" different dong",caller);i.put("dongCode","1168067000");create(i);
        i=input(" different region",caller);i.put("sigunguCode","51110");create(i);
        i=input(" different age",caller);i.put("supportAgeGroups",List.of("청년"));create(i);
        i=input(" different gender",caller);i.put("supportGender","남");create(i);
        i=input(" smaller",caller);i.put("capacity",2);create(i);
        var list=data(browser.get(search("&dongCode=1168066000&ageGroup="+encode("노년")+"&gender="+encode("여")+"&capacityMin=5&capacityMax=20")),200);
        assertThat(ids(list)).containsExactly(whole,matching);
        assertThat(data(browser.get(search("&sigunguCode=51110")),200).path("totalCount").asInt()).isEqualTo(1);
    }

    @Test
    void partialSearchEscapesWildcardsBackslashAndWithdrawnManagerNames()throws Exception {
        long literal=create(input(" %_\\!",caller));long ordinary=create(input(" ordinary",caller));
        var r=data(browser.get("/resources?resourceName="+encode("  "+marker+" %_\\!  ")),200);assertThat(ids(r)).containsExactly(literal);
        String activeName=marker+" %_\\! active";jdbc.update("UPDATE public.member SET name=? WHERE member_id=?",activeName,caller);
        // cleanup is keyed to these owned IDs; restore the marker name after the search.
        try {
            r=data(browser.get(search("&managerName="+encode("%_\\!"))),200);assertThat(ids(r)).containsExactly(literal,ordinary);
        } finally {jdbc.update("UPDATE public.member SET name=? WHERE member_id=?",marker+" member",caller);}
        long ended=create(input(" withdrawn",caller));
        jdbc.update("UPDATE public.welfare_resource SET manager_member_id=?,manual_status='종료' WHERE resource_id=?",withdrawn,ended);
        assertThat(ids(data(browser.get(search("&managerName="+encode("퇴사"))),200))).isEmpty();
        assertThat(ids(data(browser.get(search("&managerName="+encode(marker))),200))).doesNotContain(ended);
        assertThat(ids(data(browser.get(search("&managerName=%20%20")),200))).contains(ended);
    }

    @Test
    void statusAlwaysSortsFirstThenSelectedDirectionThenEndAndId()throws Exception {
        var a=input(" B",caller);a.put("capacity",4);a.put("fee",20);a.put("periodEnd",today.plusDays(20).toString());long b=create(a);
        a=input(" A",caller);a.put("capacity",2);a.put("fee",10);a.put("periodEnd",today.plusDays(10).toString());long first=create(a);
        long tie=create(a);
        a=input(" Z ended",caller);a.put("status","종료");a.put("capacity",1);a.put("fee",1);long ended=create(a);
        for(String sort:List.of("resourceName","capacity","fee","periodEnd")) {
            assertThat(ids(data(browser.get(search("&sort="+sort+"&direction=asc")),200))).containsExactly(first,tie,b,ended);
            assertThat(ids(data(browser.get(search("&sort="+sort+"&direction=desc")),200))).containsExactly(b,first,tie,ended);
        }
        assertThat(ids(data(browser.get(search("")),200))).containsExactly(first,tie,b,ended);
    }

    @Test
    void paginationClampsAndEmptyResultsKeepPageOne()throws Exception {
        create(input(" one",caller));create(input(" two",caller));long last=create(input(" three",caller));
        var r=data(browser.get(search("&size=2&page=9007199254740991")),200);
        assertThat(r.path("totalCount").asInt()).isEqualTo(3);assertThat(r.path("totalPages").asInt()).isEqualTo(2);
        assertThat(r.path("page").asInt()).isEqualTo(2);assertThat(ids(r)).containsExactly(last);
        r=data(browser.get("/resources?resourceName="+encode(marker+" missing")+"&page=50&size=2"),200);
        assertThat(r.path("totalCount").asLong()).isZero();assertThat(r.path("totalPages").asLong()).isZero();
        assertThat(r.path("page").asLong()).isEqualTo(1);assertThat(ids(r)).isEmpty();
    }

    @Test
    void endDateAndManualStatusDetermineWithdrawnManagerDisplay()throws Exception {
        for(boolean automatic:List.of(true,false)) {
            var i=input(" ended",caller);i.put("periodStart",today.minusDays(3).toString());
            i.put("periodEnd",automatic ? today.minusDays(1).toString() : today.plusDays(10).toString());
            i.put("status",automatic ? "진행 중" : "종료");long id=create(i);
            jdbc.update("UPDATE public.welfare_resource SET manager_member_id=? WHERE resource_id=?",withdrawn,id);
            var d=data(browser.get(path(id)),200);assertThat(d.path("status").asText()).isEqualTo("종료");
            assertThat(d.path("manualStatus").asText()).isEqualTo(automatic ? "진행 중" : "종료");assertThat(d.path("autoEnded").asBoolean()).isEqualTo(automatic);
            var manager=d.path("manager");assertThat(manager.path("memberId").asLong()).isEqualTo(withdrawn);
            assertThat(manager.path("name").asText()).isEqualTo("퇴사자");assertThat(manager.path("title").isNull()).isTrue();
            assertThat(manager.path("orgName").asText()).isEqualTo(marker);assertThat(manager.path("withdrawn").asBoolean()).isTrue();
            assertThat(d.path("editable").asBoolean()).isFalse();
        }
        var i=input(" ends today",caller);i.put("periodEnd",today.toString());long id=create(i);
        assertThat(data(browser.get(path(id)),200).path("status").asText()).isEqualTo("진행 중");
    }
    @Test
    void ongoingResourceWithWithdrawnManagerIsIntegrityError()throws Exception {
        long id=create(input(" inconsistent",caller));jdbc.update("UPDATE public.welfare_resource SET manager_member_id=? WHERE resource_id=?",withdrawn,id);
        error(browser.get(path(id)),500,"INTERNAL_SERVER_ERROR");
    }

    @ParameterizedTest @ValueSource(strings={"size=0","size=101","page=0","sort=unknown","direction=unknown","capacityMin=-1",
            "capacityMin=20&capacityMax=10","sigunguCode=1168","dongCode=11680660","sidoCode=51&sigunguCode=11680",
            "sigunguCode=51110&dongCode=1168066000","gender=unknown","ageGroup=unknown"})
    void invalidSearchIs400(String query)throws Exception {error(browser.get("/resources?"+query),400,"VALIDATION_ERROR");}

    @Test
    void missingIdsSecurityInvalidJsonAndCsrfKeepCommonContract()throws Exception {
        error(browser.get(path(9007199254740991L)),404,"NOT_FOUND");
        error(browser.send("PUT",path(9007199254740991L),input(" missing",caller)),404,"NOT_FOUND");
        error(browser.send("DELETE",path(9007199254740991L),null),404,"NOT_FOUND");
        error(browser.get(path(0)),400,"VALIDATION_ERROR");error(browser.get(path(9007199254740992L)),400,"VALIDATION_ERROR");
        error(new Browser().get("/resources"),401,"UNAUTHENTICATED");
        var i=input(" unknown",caller);i.put("orgId",orgs.get(1));error(browser.send("POST","/resources",i),400,"INVALID_JSON");
        error(browser.withoutCsrf("POST","/resources",input(" csrf",caller)),403,"CSRF_INVALID");
        long id=create(input(" restricted",caller));
        jdbc.update("UPDATE public.member SET temp_password_expires_at=now()+interval '1 hour' WHERE member_id=?",caller);
        var restricted=login(caller);
        for(String p:List.of("/resources",path(id)))error(restricted.get(p),403,"PASSWORD_CHANGE_REQUIRED");
        error(restricted.send("POST","/resources",input(" denied",caller)),403,"PASSWORD_CHANGE_REQUIRED");
        error(restricted.send("PUT",path(id),input(" denied",caller)),403,"PASSWORD_CHANGE_REQUIRED");
        error(restricted.send("DELETE",path(id),null),403,"PASSWORD_CHANGE_REQUIRED");
        // Earlier unrestricted session must also use the latest database flag.
        error(browser.get(path(id)),403,"PASSWORD_CHANGE_REQUIRED");
        jdbc.update("UPDATE public.member SET withdrawn_at=now() WHERE member_id=?",caller);
        error(browser.get("/resources"),401,"UNAUTHENTICATED");
    }

    private JsonNode data(HttpResponse<String> r,int status) {assertThat(r.statusCode()).isEqualTo(status);return body(r).path("data");}
    private JsonNode error(HttpResponse<String> r,int status,String code) {
        assertThat(r.statusCode()).isEqualTo(status);var b=body(r);assertThat(b.path("error").path("code").asText()).isEqualTo(code);return b.path("error");
    }
    private void fieldError(HttpResponse<String> r,String field) {
        var e=error(r,400,"VALIDATION_ERROR");var fields=new ArrayList<String>();e.path("fieldErrors").forEach(f->fields.add(f.path("field").asText()));assertThat(fields).contains(field);
    }
    private JsonNode body(HttpResponse<String> r) {
        assertThat(r.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");var b=json.readTree(r.body());
        String requestId=r.headers().firstValue("X-Request-Id").orElseThrow();UUID.fromString(requestId);assertThat(b.path("meta").path("requestId").asText()).isEqualTo(requestId);return b;
    }
    private void noContent(HttpResponse<String> r) {assertThat(r.statusCode()).isEqualTo(204);assertThat(r.body()).isEmpty();assertThat(r.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");}
    private class Browser {
        private final CookieManager cookies=new CookieManager(null,CookiePolicy.ACCEPT_ALL);
        private final HttpClient http=HttpClient.newBuilder().cookieHandler(cookies).build();
        HttpResponse<String> get(String path)throws Exception {return send("GET",path,null);}
        HttpResponse<String> send(String method,String path,Object value)throws Exception {
            var request=request(path);
            if(!method.equals("GET")) {
                assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
                String token=cookies.getCookieStore().getCookies().stream().filter(c->c.getName().equals("XSRF-TOKEN")).findFirst().orElseThrow().getValue();request.header("X-XSRF-TOKEN",token);
            }
            return execute(request,method,value);
        }
        HttpResponse<String> withoutCsrf(String method,String path,Object value)throws Exception {return execute(request(path),method,value);}
        private HttpRequest.Builder request(String path) {return HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api"+path)).timeout(Duration.ofSeconds(10));}
        private HttpResponse<String> execute(HttpRequest.Builder request,String method,Object value)throws Exception {
            if(value!=null)request.header("Content-Type","application/json");
            return http.send(request.method(method,value==null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(json.writeValueAsString(value))).build(),HttpResponse.BodyHandlers.ofString());
        }
    }
}
