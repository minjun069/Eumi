package com.eumi.backend;

import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.*;
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
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;

@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT)
class MyIntegrationTests {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired PasswordEncoder passwords;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired JsonMapper json;
    private final String marker="my-"+UUID.randomUUID().toString().substring(0,12);
    private final Map<Long,String> emails=new HashMap<>();
    private final List<Long> orgs=new ArrayList<>();
    private long caller,colleague,foreign;
    private String password;
    private Browser browser;

    @BeforeEach
    void setup()throws Exception {
        long org=organization("11680"),other=organization("51110");password=UUID.randomUUID()+"Aa1!";String hash=passwords.encode(password);
        caller=member(org,hash);colleague=member(org,hash);foreign=member(other,hash);browser=login(caller);
    }
    private long organization(String sigungu) {
        long id=jdbc.queryForObject("INSERT INTO public.organization(org_name,jurisdiction_sigungu_code,official_domain) VALUES (?,?,'eumi.test') RETURNING org_id",Long.class,marker,sigungu);orgs.add(id);return id;
    }
    private long member(long org,String hash) {
        String email="my-"+UUID.randomUUID()+"@eumi.test";
        long id=jdbc.queryForObject("INSERT INTO public.member(org_id,email_normalized,name,password_hash,title,phone) VALUES (?,?,?,?,'Synthetic original title','010-0000-0000') RETURNING member_id",Long.class,org,email,marker+" member",hash);
        emails.put(id,email);return id;
    }
    private Browser login(long member)throws Exception {
        var b=new Browser();assertThat(b.send("POST","/auth/login",Map.of("email",emails.get(member),"password",password)).statusCode()).isEqualTo(200);return b;
    }
    @AfterEach
    void cleanupOwnedRows() {
        for(long member:emails.keySet())jdbc.update("DELETE FROM public.welfare_resource WHERE manager_member_id=?",member);
        for(long member:emails.keySet()) {
            sessions.findByPrincipalName(Long.toString(member)).keySet().forEach(sessions::deleteById);
            jdbc.update("DELETE FROM public.member WHERE member_id=? AND name=?",member,marker+" member");
        }
        for(long org:orgs)jdbc.update("DELETE FROM public.organization WHERE org_id=? AND org_name=?",org,marker);
    }

    @Test
    void infoUsesOnlyCurrentMemberAndFullOrganizationJurisdiction()throws Exception {
        var info=data(browser.get("/members/me"));assertThat(info.size()).isEqualTo(6);
        assertThat(info.path("name").asText()).isEqualTo(marker+" member");assertThat(info.path("email").asText()).isEqualTo(emails.get(caller));
        assertThat(info.path("orgName").asText()).isEqualTo(marker);assertThat(info.path("jurisdictionName").asText()).isEqualTo("서울특별시 강남구");
        info=data(login(foreign).get("/members/me"));assertThat(info.path("email").asText()).isEqualTo(emails.get(foreign));
        assertThat(info.path("jurisdictionName").asText()).isEqualTo("강원특별자치도 춘천시");
    }

    @Test
    void patchSeparatesOmissionNullAndEmptyTitleAndDoesNotRotateOrDeleteSessions()throws Exception {
        var another=login(caller);String session=browser.session();
        var before=sessions.findByPrincipalName(Long.toString(caller)).keySet();assertThat(before).hasSize(2);
        jdbc.update("UPDATE public.member SET updated_at=TIMESTAMPTZ '2000-01-01 00:00:00+09' WHERE member_id=?",caller);
        var info=data(browser.send("PATCH","/members/me",Map.of("title"," Synthetic changed ")));
        assertThat(info.path("title").asText()).isEqualTo("Synthetic changed");assertThat(info.path("phone").asText()).isEqualTo("010-0000-0000");
        assertThat(data(browser.get("/auth/me")).path("title").asText()).isEqualTo("Synthetic changed");
        assertThat(jdbc.queryForObject("SELECT updated_at>TIMESTAMPTZ '2000-01-01 00:00:00+09' FROM public.member WHERE member_id=?",Boolean.class,caller)).isTrue();
        var patch=new HashMap<String,Object>();patch.put("phone",null);info=data(browser.send("PATCH","/members/me",patch));
        assertThat(info.path("title").asText()).isEqualTo("Synthetic changed");assertThat(info.has("phone") && info.path("phone").isNull()).isTrue();
        info=data(browser.send("PATCH","/members/me",Map.of("title","   ")));
        assertThat(info.has("title") && info.path("title").isNull()).isTrue();assertThat(info.path("phone").isNull()).isTrue();
        info=data(browser.send("PATCH","/members/me",Map.of("phone"," 011-000-0000 ")));
        assertThat(info.path("phone").asText()).isEqualTo("011-000-0000");assertThat(info.path("title").isNull()).isTrue();
        patch=new HashMap<>();patch.put("title",null);patch.put("phone",null);info=data(browser.send("PATCH","/members/me",patch));
        assertThat(info.path("title").isNull() && info.path("phone").isNull()).isTrue();
        assertThat(browser.session()).isEqualTo(session);
        assertThat(sessions.findByPrincipalName(Long.toString(caller)).keySet()).containsExactlyInAnyOrderElementsOf(before);
        assertThat(data(another.get("/members/me")).path("title").isNull()).isTrue();
        assertThat(data(login(colleague).get("/members/me")).path("title").asText()).isEqualTo("Synthetic original title");
    }

    @ParameterizedTest @ValueSource(strings={"", " ","01000000000","012-0000-0000","010-00-0000","010-00000-0000"})
    void badPhoneIsFieldErrorAndDoesNotPartiallyUpdateTitle(String phone)throws Exception {
        var e=error(browser.send("PATCH","/members/me",Map.of("phone",phone,"title","Synthetic rejected")),400,"VALIDATION_ERROR");
        assertThat(e.path("fieldErrors").get(0).path("field").asText()).isEqualTo("phone");
        var info=data(browser.get("/members/me"));assertThat(info.path("title").asText()).isEqualTo("Synthetic original title");assertThat(info.path("phone").asText()).isEqualTo("010-0000-0000");
    }

    @Test
    void titleUsesCodePointsAndInvalidShapeCannotChangeProtectedFields()throws Exception {
        var emoji="😀".repeat(100);assertThat(data(browser.send("PATCH","/members/me",Map.of("title",emoji))).path("title").asText()).isEqualTo(emoji);
        var e=error(browser.send("PATCH","/members/me",Map.of("title",emoji+"😀")),400,"VALIDATION_ERROR");
        assertThat(e.path("fieldErrors").get(0).path("field").asText()).isEqualTo("title");
        error(browser.send("PATCH","/members/me",Map.of()),400,"VALIDATION_ERROR");
        for(String key:List.of("name","email","orgName","jurisdictionName","memberId"))error(browser.send("PATCH","/members/me",Map.of(key,"Synthetic denied")),400,"INVALID_JSON");
        for(Object bad:List.of(List.of(),Map.of("title",123),Map.of("phone",false)))error(browser.send("PATCH","/members/me",bad),400,"INVALID_JSON");
        assertThat(data(browser.get("/members/me")).path("title").asText()).isEqualTo(emoji);
    }

    private long resource(long manager,String status,int endDays,boolean deleted) {
        return jdbc.queryForObject("""
                INSERT INTO public.welfare_resource(resource_name,operating_org_name,target,support_age_groups,support_gender,
                sigungu_code,period_start,period_end,fee,manual_status,manager_member_id,capacity,deleted_at)
                VALUES (?,'Synthetic org','Synthetic target',ARRAY['무관'],'무관','11680',current_date-20,current_date+?,0,?,?,5,
                CASE WHEN ? THEN now() ELSE NULL END) RETURNING resource_id
                """,Long.class,marker+" resource",endDays,status,manager,deleted);
    }
    @Test
    void ownedResourcesReturnEveryVisibleRowInStatusEndAndIdOrder()throws Exception {
        assertThat(data(browser.get("/members/me/resources")).path("totalCount").asLong()).isZero();
        var expected=new ArrayList<Long>();long later=resource(caller,"진행 중",10,false);
        for(int i=0;i<12;i++)expected.add(resource(caller,"진행 중",5,false));
        expected.add(later);expected.add(resource(caller,"진행 중",-1,false));expected.add(resource(caller,"종료",20,false));
        long other=resource(colleague,"진행 중",1,false),foreignResource=resource(foreign,"진행 중",1,false),deleted=resource(caller,"진행 중",1,true);
        var page=data(browser.get("/members/me/resources"));assertThat(page.size()).isEqualTo(2);
        assertThat(page.path("totalCount").asLong()).isEqualTo(15);var actual=new ArrayList<Long>();
        for(var item:page.path("items")) {assertThat(item.size()).isEqualTo(11);actual.add(item.path("resourceId").asLong());assertThat(item.has("dongName") && item.path("dongName").isNull()).isTrue();}
        assertThat(actual).containsExactlyElementsOf(expected).doesNotContain(other,foreignResource,deleted);
        assertThat(page.path("items").get(13).path("status").asText()).isEqualTo("종료");
        assertThat(data(login(colleague).get("/members/me/resources")).path("totalCount").asLong()).isEqualTo(1);
        assertThat(data(login(foreign).get("/members/me/resources")).path("items").get(0).path("resourceId").asLong()).isEqualTo(foreignResource);
    }

    @Test
    void unauthenticatedRestrictedAndWithdrawnMembersCannotReadOrPatch()throws Exception {
        var anonymous=new Browser();for(String path:List.of("/members/me","/members/me/resources"))error(anonymous.get(path),401,"UNAUTHENTICATED");
        error(anonymous.send("PATCH","/members/me",Map.of("title","Synthetic denied")),401,"UNAUTHENTICATED");
        jdbc.update("UPDATE public.member SET temp_password_expires_at=now()+interval '1 hour' WHERE member_id=?",caller);
        var restricted=login(caller);
        for(var b:List.of(browser,restricted)) {
            for(String path:List.of("/members/me","/members/me/resources"))error(b.get(path),403,"PASSWORD_CHANGE_REQUIRED");
            error(b.send("PATCH","/members/me",Map.of("title","Synthetic denied")),403,"PASSWORD_CHANGE_REQUIRED");
        }
        jdbc.update("UPDATE public.member SET withdrawn_at=now() WHERE member_id=?",caller);
        for(String path:List.of("/members/me","/members/me/resources"))error(browser.get(path),401,"UNAUTHENTICATED");
        error(browser.send("PATCH","/members/me",Map.of("title","Synthetic denied")),401,"UNAUTHENTICATED");
    }
    @Test
    void patchRequiresCsrf()throws Exception {error(browser.withoutCsrf("PATCH","/members/me",Map.of("title","Synthetic denied")),403,"CSRF_INVALID");}

    private JsonNode data(HttpResponse<String> r) {assertThat(r.statusCode()).isEqualTo(200);return body(r).path("data");}
    private JsonNode error(HttpResponse<String> r,int status,String code) {assertThat(r.statusCode()).isEqualTo(status);var e=body(r).path("error");assertThat(e.path("code").asText()).isEqualTo(code);return e;}
    private JsonNode body(HttpResponse<String> r) {
        assertThat(r.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");var b=json.readTree(r.body());
        String id=r.headers().firstValue("X-Request-Id").orElseThrow();UUID.fromString(id);assertThat(b.path("meta").path("requestId").asText()).isEqualTo(id);return b;
    }
    private class Browser {
        private final CookieManager cookies=new CookieManager(null,CookiePolicy.ACCEPT_ALL);
        private final HttpClient http=HttpClient.newBuilder().cookieHandler(cookies).build();
        HttpResponse<String> get(String path)throws Exception {return send("GET",path,null);}
        String session() {return cookies.getCookieStore().getCookies().stream().filter(c->c.getName().equals("SESSION")).findFirst().orElseThrow().getValue();}
        HttpResponse<String> send(String method,String path,Object value)throws Exception {
            var request=request(path);if(!method.equals("GET")) {
                assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
                String token=cookies.getCookieStore().getCookies().stream().filter(c->c.getName().equals("XSRF-TOKEN")).findFirst().orElseThrow().getValue();request.header("X-XSRF-TOKEN",token);
            }
            return execute(request,method,value);
        }
        HttpResponse<String> withoutCsrf(String method,String path,Object value)throws Exception {return execute(request(path),method,value);}
        private HttpRequest.Builder request(String path) {return HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api"+path)).timeout(Duration.ofSeconds(10));}
        private HttpResponse<String> execute(HttpRequest.Builder request,String method,Object value)throws Exception {
            if(value!=null)request.header("Content-Type","application/json");
            return http.send(request.method(method,value==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(value))).build(),HttpResponse.BodyHandlers.ofString());
        }
    }
}
