package com.eumi.backend;

import java.net.*;
import java.net.http.*;
import java.security.MessageDigest;
import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.regex.Pattern;
import com.eumi.backend.auth.signup.*;
import com.eumi.backend.common.error.*;
import com.eumi.backend.support.MailpitTestInbox;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.*;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mail.MailSendException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.session.jdbc.JdbcIndexedSessionRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.convention.TestBean;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;
import static org.assertj.core.api.SoftAssertions.assertSoftly;
import static org.mockito.Mockito.*;

/** 실제 PostgreSQL·Mailpit·HTTP. 코드·증명·암호·수신자는 메모리에만 두고 자체 fixture만 지운다. */
@Tag("local-integration")
@ActiveProfiles("local")
@ExtendWith(OutputCaptureExtension.class)
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.DEFINED_PORT,
        properties={"server.port=${EUMI_SIGNUP_TEST_PORT:0}","eumi.ai.mode=fake","spring.datasource.hikari.minimum-idle=1"})
class SignupIntegrationTests {
    private static final Instant NOW=Instant.now().truncatedTo(ChronoUnit.SECONDS);
    private static final String SEND="/signup/email-verifications",VERIFY=SEND+"/verify";
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired JsonMapper json;
    @Autowired JdbcIndexedSessionRepository sessions;
    @Autowired SignupSecrets secrets;
    @TestBean(methodName="signupClock") Clock clock;
    static Clock signupClock() {return Clock.fixed(NOW,ZoneOffset.UTC);}
    @MockitoSpyBean SignupRepository repository;
    @MockitoSpyBean PasswordEncoder passwords;
    @MockitoSpyBean JavaMailSender sender;
    private final String marker="a2-signup-"+UUID.randomUUID();
    private final String domain="a2-"+UUID.randomUUID()+".eumi.test";
    private final String password=" "+UUID.randomUUID()+"Aa1! ";
    private final Map<Long,String> organizations=new LinkedHashMap<>();
    private final Set<String> recipients=new HashSet<>();
    private long org,otherOrg;
    private Browser browser;
    private MailpitTestInbox inbox;

    @BeforeEach void setup() {
        inbox=new MailpitTestInbox(json);browser=new Browser();
        org=organization(marker+" base A",domain);otherOrg=organization(marker+" base B",UUID.randomUUID()+".eumi.test");
    }
    private long organization(String name,String officialDomain) {
        long id=jdbc.queryForObject("INSERT INTO public.organization(org_name,jurisdiction_sigungu_code,official_domain) VALUES (?,'11680',?) RETURNING org_id",
                Long.class,name,officialDomain);organizations.put(id,name);return id;
    }
    private String email() {String value=UUID.randomUUID()+"@"+domain;recipients.add(value);return value;}
    @AfterEach void cleanup() throws Exception {
        reset(repository,passwords,sender);
        try {
            for(var entry:organizations.entrySet()) {
                jdbc.update("DELETE FROM public.email_verification WHERE org_id=?",entry.getKey());
                var members=jdbc.queryForList("SELECT member_id FROM public.member WHERE org_id=?",Long.class,entry.getKey());
                for(long id:members) sessions.findByPrincipalName(Long.toString(id)).keySet().forEach(sessions::deleteById);
                jdbc.update("DELETE FROM public.member WHERE org_id=?",entry.getKey());
                jdbc.update("DELETE FROM public.organization WHERE org_id=? AND org_name=?",entry.getKey(),entry.getValue());
            }
        } finally {if(inbox!=null) inbox.deleteOwned(recipients);}
    }
    private SignupRepository.Verification row(String email) {return repository.verification(email,false).orElseThrow();}
    private long memberCount(String email) {return jdbc.queryForObject("SELECT count(*) FROM public.member WHERE email_normalized=?",Long.class,email);}
    private Map<String,Object> signup(String email,String proof) {
        return new HashMap<>(Map.of("verificationToken",proof,"orgId",org,"email",email,"name","  "+marker+"  ","password",password,"title",""));
    }
    private String proof(String email,String code) throws Exception {
        var token=data(browser.post(VERIFY,Map.of("email",email,"code",code)),200).path("verificationToken").asText();
        assertThat(token.matches("[A-Za-z0-9_-]{43}")).isTrue();return token;
    }
    private Issued issue(String email) throws Exception {return issue(email,email);}
    private Issued issue(String email,String requestEmail) throws Exception {
        var before=new HashSet<>(inbox.ids(Set.of(email)));
        var result=data(browser.post(SEND,Map.of("orgId",org,"email",requestEmail)),201);
        String expiration=result.path("expiresAt").asText();
        assertThat(expiration.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\+09:00")).isTrue();
        var expires=OffsetDateTime.parse(expiration).toInstant();assertThat(Duration.between(clock.instant(),expires)).isEqualTo(Duration.ofMinutes(10));
        List<String> fresh;long deadline=System.nanoTime()+Duration.ofSeconds(5).toNanos();
        do {
            fresh=inbox.ids(Set.of(email)).stream().filter(id->!before.contains(id)).toList();
            if(!fresh.isEmpty()) break;Thread.sleep(20);
        } while(System.nanoTime()<deadline);
        assertThat(fresh.size()).isEqualTo(1);var message=inbox.message(fresh.getFirst());
        assertThat(message.path("Subject").asText()).isEqualTo("[이음이] 가입 인증 코드");
        String text=message.path("Text").asText();var match=Pattern.compile("(?m)^인증 코드: ([0-9]{6})\\r?$").matcher(text);
        assertThat(match.find()).isTrue();assertThat(text.contains("10분 동안 유효")&&text.contains(expiration)).isTrue();
        assertThat(text.contains(email)||text.contains(marker)).isFalse();return new Issued(match.group(1),expires);
    }
    private record Issued(String code,Instant expires) {@Override public String toString(){return "Issued[redacted]";}}
    private void age(String email) {jdbc.update("UPDATE public.email_verification SET created_at=? WHERE email_normalized=?",clock.instant().minusSeconds(61).atOffset(ZoneOffset.UTC),email);}
    private String wrongCode(String correct) {return String.format(Locale.ROOT,"%06d",(Integer.parseInt(correct)+1)%1_000_000);}
    private AtomicInteger countHashes(AtomicBoolean insideTransaction) {
        var count=new AtomicInteger();
        doAnswer(call->{count.incrementAndGet();if(TransactionSynchronizationManager.isActualTransactionActive() || TransactionSynchronizationManager.hasResource(jdbc.getDataSource())) insideTransaction.set(true);return call.callRealMethod();})
                .when(passwords).encode(any());return count;
    }
    private void existingMember(String email,boolean withdrawn) {
        jdbc.update("INSERT INTO public.member(org_id,email_normalized,name,password_hash,withdrawn_at) VALUES (?,?,?,?,?)",org,email,marker,
                UUID.randomUUID().toString(),withdrawn ? clock.instant().atOffset(ZoneOffset.UTC) : null);
    }

    @Test void organizationsArePublicAndSearchSpecialCharactersLiterallyWithCorrectJurisdiction() throws Exception {
        for(String literal:List.of("%","_","\\")) {
            long id=organization(marker+" literal "+literal,domain);
            var list=data(browser.get("/organizations?keyword="+encode(marker+" literal "+literal)),200);
            assertThat(list.size()).isEqualTo(1);assertThat(list.get(0).path("orgId").asLong()).isEqualTo(id);
            assertThat(list.get(0).path("sidoName").asText()).isEqualTo("서울특별시");
            assertThat(list.get(0).path("sigunguName").asText()).isEqualTo("강남구");
            assertThat(list.get(0).path("officialDomain").asText().equals(domain)).isTrue();
        }
    }
    @Test void organizationsSortByNameAndIdAndStopAt20() throws Exception {
        var expected=new ArrayList<String>();
        for(int i=22;i>=0;i--) {String name=marker+" cap "+String.format(Locale.ROOT,"%02d",i);organization(name,domain);expected.add(name);}
        expected.sort(String::compareTo);var list=data(browser.get("/organizations?keyword="+encode(marker+" cap")),200);
        assertThat(list.size()).isEqualTo(20);
        assertThat(list.valueStream().map(v->v.path("orgName").asText()).toList()).containsExactlyElementsOf(expected.subList(0,20));
    }
    @ParameterizedTest @ValueSource(strings={"missing","blank","oversize"})
    void invalidOrganizationKeywordsReturnAFieldError(String scenario) throws Exception {
        String path="/organizations";
        if(!scenario.equals("missing")) path+="?keyword="+encode(scenario.equals("blank") ? "   " : "😀".repeat(201));
        var result=browser.get(path);error(result,400,"VALIDATION_ERROR");assertField(result,"keyword");
    }
    @Test void fullMailpitSignupFlowStoresOnlyHashesAndDoesNotAutomaticallyLogIn(CapturedOutput output) throws Exception {
        String email=email();var sent=issue(email,"  "+email.toUpperCase(Locale.ROOT)+"  ");var before=row(email);
        assertThat(MessageDigest.isEqual(before.codeHash(),secrets.codeHash(email,sent.code()))).isTrue();assertThat(before.codeHash().length).isEqualTo(32);
        assertThat(before.createdAt()).isEqualTo(clock.instant());assertThat(before.expiresAt()).isEqualTo(sent.expires());
        assertThat(before.verifiedAt()==null && before.proofHash()==null && before.proofExpiresAt()==null).isTrue();
        String token=proof("  "+email.toUpperCase(Locale.ROOT)+"  ",sent.code());var verified=row(email);
        assertThat(MessageDigest.isEqual(verified.proofHash(),secrets.proofHash(token))).isTrue();assertThat(verified.proofHash().length).isEqualTo(32);
        assertThat(verified.verifiedAt()).isEqualTo(clock.instant());assertThat(verified.proofExpiresAt()).isEqualTo(clock.instant().plusSeconds(600));
        var inTransaction=new AtomicBoolean();var calls=countHashes(inTransaction);
        var input=signup("  "+email.toUpperCase(Locale.ROOT)+"  ",token);var response=browser.post("/members",input);
        long id=data(response,201).path("memberId").asLong();
        assertThat(calls.get()).isEqualTo(1);assertThat(inTransaction.get()).isFalse();
        assertThat(response.headers().allValues("Set-Cookie").stream().noneMatch(v->v.regionMatches(true,0,"SESSION=",0,8))).isTrue();
        assertThat(repository.verification(email,false).isEmpty()).isTrue();
        assertThat(jdbc.queryForObject("SELECT title IS NULL AND phone IS NULL AND name=? FROM public.member WHERE member_id=?",Boolean.class,marker,id)).isTrue();
        assertThat(jdbc.queryForObject("SELECT created_at=? AND updated_at=? FROM public.member WHERE member_id=?",Boolean.class,
                clock.instant().atOffset(ZoneOffset.UTC),clock.instant().atOffset(ZoneOffset.UTC),id)).isTrue();
        String hash=jdbc.queryForObject("SELECT password_hash FROM public.member WHERE member_id=?",String.class,id);
        assertThat(hash.equals(password)).isFalse();assertThat(passwords.matches(password,hash)).isTrue();
        error(browser.get("/auth/me"),401,"UNAUTHENTICATED");
        data(browser.post("/auth/login",Map.of("email",email,"password",password)),200);
        assertThat(data(browser.get("/auth/me"),200).path("memberId").asLong()).isEqualTo(id);
        error(new Browser().post("/members",signup(email,token)),400,"PROOF_INVALID");
        assertThat(output.getAll().contains(email)||output.getAll().contains(sent.code())||output.getAll().contains(token)||output.getAll().contains(password)).isFalse();
    }
    @ParameterizedTest @ValueSource(strings={"different","subdomain"})
    void onlyTheExactOfficialDomainIsAccepted(String scenario) throws Exception {
        String email=UUID.randomUUID()+"@"+(scenario.equals("subdomain") ? "sub."+domain : UUID.randomUUID()+".test");recipients.add(email);
        error(browser.post(SEND,Map.of("orgId",org,"email",email)),400,"EMAIL_DOMAIN_MISMATCH");
        assertThat(repository.verification(email,false).isEmpty()).isTrue();assertThat(inbox.ids(Set.of(email)).isEmpty()).isTrue();
    }
    @ParameterizedTest @ValueSource(booleans={false,true})
    void activeAndWithdrawnEmailsCannotReceiveSignupMail(boolean withdrawn) throws Exception {
        String email=email();existingMember(email,withdrawn);
        var response=browser.post(SEND,Map.of("orgId",org,"email",email));error(response,409,"EMAIL_ALREADY_EXISTS");
        assertThat(body(response).path("error").path("message").asText()).isEqualTo("이미 가입된 이메일입니다.");
        assertThat(inbox.ids(Set.of(email)).isEmpty()).isTrue();
    }
    @Test void missingOrganizationHasA400OrgIdFieldError() throws Exception {
        String email=email();var response=browser.post(SEND,Map.of("orgId",9007199254740991L,"email",email));
        error(response,400,"VALIDATION_ERROR");assertField(response,"orgId");assertThat(inbox.ids(Set.of(email)).isEmpty()).isTrue();
    }
    @Test void resendWaits60SecondsRotatesTheCodeAndInvalidatesProof() throws Exception {
        String email=email();var old=issue(email);String oldProof=proof(email,old.code());int count=inbox.ids(Set.of(email)).size();
        var limited=browser.post(SEND,Map.of("orgId",org,"email",email));error(limited,429,"RATE_LIMITED");
        assertThat(body(limited).path("error").path("message").asText()).isEqualTo("요청을 처리하지 못했습니다.");
        assertThat(inbox.ids(Set.of(email)).size()).isEqualTo(count);age(email);var next=issue(email);
        assertThat(next.code().equals(old.code())).isFalse();
        error(browser.post(VERIFY,Map.of("email",email,"code",old.code())),400,"VERIFICATION_INVALID");
        error(browser.post("/members",signup(email,oldProof)),400,"PROOF_INVALID");
        assertThat(row(email).verifiedAt()==null && row(email).proofHash()==null && row(email).proofExpiresAt()==null).isTrue();
        proof(email,next.code());
    }
    @Test void allFiveWrongAttemptsCommitBefore400AndThenTheCorrectCodeIsRejected() throws Exception {
        String email=email();var sent=issue(email);
        for(int attempt=1;attempt<=5;attempt++) {
            error(browser.post(VERIFY,Map.of("email",email,"code",wrongCode(sent.code()))),400,"VERIFICATION_INVALID");
            assertThat(row(email).failedAttempts()).isEqualTo(attempt);
        }
        error(browser.post(VERIFY,Map.of("email",email,"code",sent.code())),400,"VERIFICATION_INVALID");
        assertThat(row(email).failedAttempts()).isEqualTo(5);
    }
    @ParameterizedTest @ValueSource(booleans={false,true})
    void codeAtOrPastItsExpiryIsRejected(boolean past) throws Exception {
        String email=email();var sent=issue(email);
        jdbc.update("UPDATE public.email_verification SET expires_at=? WHERE email_normalized=?",clock.instant().minusSeconds(past ? 1 : 0).atOffset(ZoneOffset.UTC),email);
        error(browser.post(VERIFY,Map.of("email",email,"code",sent.code())),400,"VERIFICATION_EXPIRED");
        assertThat(row(email).failedAttempts()).isZero();
    }
    @Test void verificationWithoutARowIsInvalid() throws Exception {
        error(browser.post(VERIFY,Map.of("email",email(),"code",secrets.code())),400,"VERIFICATION_INVALID");
    }
    @Test void checkingTheCodeAgainRotatesTheProofAndRejectsTheOldOneWithoutHashing() throws Exception {
        String email=email();var sent=issue(email);String first=proof(email,sent.code()),second=proof(email,sent.code());
        assertThat(first.equals(second)).isFalse();var calls=countHashes(new AtomicBoolean());
        error(browser.post("/members",signup(email,first)),400,"PROOF_INVALID");assertThat(calls.get()).isZero();
        data(browser.post("/members",signup(email,second)),201);assertThat(calls.get()).isEqualTo(1);
    }
    @ParameterizedTest @ValueSource(booleans={false,true})
    void proofAtOrPastItsExpiryIsRejectedWithoutPbkdf2(boolean past) throws Exception {
        String email=email();String token=proof(email,issue(email).code());
        jdbc.update("UPDATE public.email_verification SET proof_expires_at=? WHERE email_normalized=?",clock.instant().minusSeconds(past ? 1 : 0).atOffset(ZoneOffset.UTC),email);
        var calls=countHashes(new AtomicBoolean());error(browser.post("/members",signup(email,token)),400,"PROOF_EXPIRED");assertThat(calls.get()).isZero();
    }
    @ParameterizedTest @ValueSource(strings={"token","organization","email","missing"})
    void invalidProofIsRejectedBeforeAnyPasswordHash(String scenario) throws Exception {
        String email=email();String token=scenario.equals("missing") ? secrets.proof() : proof(email,issue(email).code());
        var input=signup(email,scenario.equals("token") ? secrets.proof() : token);
        if(scenario.equals("organization")) input.put("orgId",otherOrg);
        if(scenario.equals("email")) input.put("email",email());
        var calls=countHashes(new AtomicBoolean());error(browser.post("/members",input),400,"PROOF_INVALID");
        assertThat(calls.get()).isZero();assertThat(memberCount(email)).isZero();
    }
    @Test void duplicateMemberAppearingAfterPrecheckIsRejectedUnderTheVerificationLock() throws Exception {
        String email=email();String token=proof(email,issue(email).code());var once=new AtomicBoolean();
        doAnswer(call->{Object hash=call.callRealMethod();if(once.compareAndSet(false,true)) existingMember(email,false);return hash;}).when(passwords).encode(any());
        var response=browser.post("/members",signup(email,token));error(response,409,"EMAIL_ALREADY_EXISTS");
        assertThat(body(response).path("error").path("message").asText()).isEqualTo("이미 가입된 이메일입니다.");
        assertThat(memberCount(email)).isEqualTo(1);assertThat(repository.verification(email,false).isPresent()).isTrue();
    }
    @Test void theMemberEmailUniqueViolationAlsoReturns409AndKeepsTheProof() throws Exception {
        String email=email();String token=proof(email,issue(email).code());
        doAnswer(call->{existingMember(email,false);return call.callRealMethod();}).when(repository).insertMember(any(),anyString(),any());
        error(browser.post("/members",signup(email,token)),409,"EMAIL_ALREADY_EXISTS");
        // 실패를 주입한 INSERT도 같은 테스트 트랜잭션이므로 둘 다 롤백되고 증명 행은 남는다.
        assertThat(memberCount(email)).isZero();assertThat(repository.verification(email,false).isPresent()).isTrue();
        reset(repository);data(browser.post("/members",signup(email,token)),201);
    }
    @Test void proofChangedAfterHashingIsRecheckedAndCannotCreateAMember() throws Exception {
        String email=email();String token=proof(email,issue(email).code());var id=row(email).id();
        doAnswer(call->{Object hash=call.callRealMethod();repository.verify(id,secrets.proofHash(secrets.proof()),clock.instant(),clock.instant().plusSeconds(600));return hash;})
                .when(passwords).encode(any());
        error(browser.post("/members",signup(email,token)),400,"PROOF_INVALID");assertThat(memberCount(email)).isZero();
    }
    @Test void concurrentSignupConsumesTheProofExactlyOnce() throws Exception {
        String email=email();String token=proof(email,issue(email).code());var ready=new CountDownLatch(2);var gate=new CountDownLatch(1);
        doAnswer(call->{Object result=call.callRealMethod();if(!call.getArgument(1,Boolean.class)) {ready.countDown();if(!gate.await(8,TimeUnit.SECONDS)) throw new IllegalStateException("Synthetic signup gate timeout");}return result;})
                .when(repository).verification(eq(email),eq(false));
        try(var executor=Executors.newFixedThreadPool(2)) {
            var first=executor.submit(()->new Browser().post("/members",signup(email,token)));
            var second=executor.submit(()->new Browser().post("/members",signup(email,token)));
            try {assertThat(ready.await(5,TimeUnit.SECONDS)).isTrue();} finally {gate.countDown();}
            var a=first.get(15,TimeUnit.SECONDS);var b=second.get(15,TimeUnit.SECONDS);
            assertThat(List.of(a.statusCode(),b.statusCode())).containsExactlyInAnyOrder(201,400);
            data(a.statusCode()==201 ? a : b,201);error(a.statusCode()==400 ? a : b,400,"PROOF_INVALID");
        }
        assertThat(memberCount(email)).isEqualTo(1);assertThat(repository.verification(email,false).isEmpty()).isTrue();
    }
    @Test void simultaneousFirstSendsReturnOne201AndOne429AndOnlyOneMail() throws Exception {
        String email=email();var ready=new CountDownLatch(2);var gate=new CountDownLatch(1);
        doAnswer(call->{Object result=call.callRealMethod();ready.countDown();if(!gate.await(8,TimeUnit.SECONDS)) throw new IllegalStateException("Synthetic send gate timeout");return result;})
                .when(repository).verification(eq(email),eq(true));
        try(var executor=Executors.newFixedThreadPool(2)) {
            var first=executor.submit(()->new Browser().post(SEND,Map.of("orgId",org,"email",email)));
            var second=executor.submit(()->new Browser().post(SEND,Map.of("orgId",org,"email",email)));
            try {assertThat(ready.await(5,TimeUnit.SECONDS)).isTrue();} finally {gate.countDown();}
            var a=first.get(15,TimeUnit.SECONDS);var b=second.get(15,TimeUnit.SECONDS);
            assertThat(List.of(a.statusCode(),b.statusCode())).containsExactlyInAnyOrder(201,429);
            data(a.statusCode()==201 ? a : b,201);error(a.statusCode()==429 ? a : b,429,"RATE_LIMITED");
        }
        assertThat(inbox.ids(Set.of(email)).size()).isEqualTo(1);assertThat(row(email).failedAttempts()).isZero();
    }
    @Test void simultaneousResendsWithAnExistingRowReturnOne201AndOne429AndOnlyOneNewMail() throws Exception {
        String email=email();issue(email);age(email);var previous=row(email);
        var oldMailIds=new HashSet<>(inbox.ids(Set.of(email)));
        var mailReady=new CountDownLatch(1);var secondReady=new CountDownLatch(1);var releaseMail=new CountDownLatch(1);
        var firstPid=new AtomicInteger();var secondPid=new AtomicInteger();var reads=new AtomicInteger();
        var pauseFirstMail=new AtomicBoolean();var secondSawMissingRow=new AtomicBoolean();
        doAnswer(call->{
            if(pauseFirstMail.compareAndSet(false,true)) {
                firstPid.set(jdbc.queryForObject("SELECT pg_backend_pid()",Integer.class));mailReady.countDown();
                if(!releaseMail.await(10,TimeUnit.SECONDS)) throw new IllegalStateException("Synthetic resend mail gate timeout");
            }
            return call.callRealMethod();
        }).when(sender).send(any(SimpleMailMessage.class));
        doAnswer(call->{
            int order=reads.incrementAndGet();
            if(order==2) {secondPid.set(jdbc.queryForObject("SELECT pg_backend_pid()",Integer.class));secondReady.countDown();}
            Object result=call.callRealMethod();
            if(order==2) secondSawMissingRow.set(((Optional<?>)result).isEmpty());
            return result;
        }).when(repository).verification(eq(email),eq(true));
        try(var executor=Executors.newFixedThreadPool(2)) {
            var first=executor.submit(()->new Browser().post(SEND,Map.of("orgId",org,"email",email)));
            Future<HttpResponse<String>> second;
            try {
                assertThat(mailReady.await(5,TimeUnit.SECONDS)).as("first resend holds its transaction before SMTP").isTrue();
                second=executor.submit(()->new Browser().post(SEND,Map.of("orgId",org,"email",email)));
                assertThat(secondReady.await(3,TimeUnit.SECONDS)).isTrue();
                assertThat(awaitBlockedVerificationSelect(secondPid.get(),firstPid.get())).as("second resend waits for the first verification row").isTrue();
            } finally {releaseMail.countDown();}
            var a=first.get(15,TimeUnit.SECONDS);var b=second.get(15,TimeUnit.SECONDS);
            assertThat(secondSawMissingRow.get()).as("deleted row is absent after the waiting SELECT FOR UPDATE").isTrue();
            var fresh=inbox.ids(Set.of(email)).stream().filter(id->!oldMailIds.contains(id)).toList();
            assertSoftly(check->{
                check.assertThat(List.of(a.statusCode(),b.statusCode())).containsExactlyInAnyOrder(201,429);
                check.assertThat(fresh.size()).as("new Mailpit messages after concurrent resends").isEqualTo(1);
            });
            data(a,201);error(b,429,"RATE_LIMITED");
            var after=row(email);assertThat(after.id()).isNotEqualTo(previous.id());assertThat(after.createdAt()).isEqualTo(clock.instant());
            assertThat(after.failedAttempts()).isZero();assertThat(after.verifiedAt()==null && after.proofHash()==null && after.proofExpiresAt()==null).isTrue();
            var match=Pattern.compile("(?m)^인증 코드: ([0-9]{6})\\r?$").matcher(inbox.message(fresh.getFirst()).path("Text").asText());
            assertThat(match.find()).isTrue();proof(email,match.group(1));
        }
    }
    private boolean awaitBlockedVerificationSelect(int requestPid,int blockerPid) throws InterruptedException {
        long deadline=System.nanoTime()+Duration.ofSeconds(3).toNanos();
        do {
            if(Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=? AND wait_event_type='Lock' "
                    +"AND upper(query) LIKE '%FOR UPDATE%' AND ?=ANY(pg_blocking_pids(pid)))",Boolean.class,requestPid,blockerPid))) return true;
            Thread.sleep(20);
        } while(System.nanoTime()<deadline);
        return false;
    }
    @ParameterizedTest @ValueSource(booleans={false,true})
    void mailFailureRollsBackANewOrReplacedVerification(boolean resend) throws Exception {
        String email=email();SignupRepository.Verification previous=null;
        if(resend) {var sent=issue(email);proof(email,sent.code());age(email);previous=row(email);}
        int count=inbox.ids(Set.of(email)).size();
        doThrow(new MailSendException("Synthetic mail failure")).when(sender).send(any(SimpleMailMessage.class));
        error(browser.post(SEND,Map.of("orgId",org,"email",email)),500,"INTERNAL_SERVER_ERROR");
        reset(sender);assertThat(inbox.ids(Set.of(email)).size()).isEqualTo(count);
        if(previous==null) assertThat(repository.verification(email,false).isEmpty()).isTrue();
        else {
            var after=row(email);assertThat(after.id()).isEqualTo(previous.id());
            assertThat(MessageDigest.isEqual(after.codeHash(),previous.codeHash())&&MessageDigest.isEqual(after.proofHash(),previous.proofHash())).isTrue();
            assertThat(after.createdAt()).isEqualTo(previous.createdAt());assertThat(after.proofExpiresAt()).isEqualTo(previous.proofExpiresAt());
        }
        issue(email);
    }
    @Test void memberAndProofDeletionAreAtomicWhenTheLastWriteFails() throws Exception {
        String email=email();String token=proof(email,issue(email).code());
        doThrow(new IllegalStateException("Synthetic proof deletion fault")).when(repository).deleteVerification(any());
        error(browser.post("/members",signup(email,token)),500,"INTERNAL_SERVER_ERROR");
        assertThat(memberCount(email)).isZero();assertThat(repository.verification(email,false).isPresent()).isTrue();reset(repository);
        data(browser.post("/members",signup(email,token)),201);
    }
    @Test void signupTrimsOptionalTitleAndPhoneBeforeSaving() throws Exception {
        String email=email();String token=proof(email,issue(email).code());var input=signup(email,token);
        String phone=String.format(Locale.ROOT,"010-%04d-%04d",new java.security.SecureRandom().nextInt(10000),new java.security.SecureRandom().nextInt(10000));
        input.put("title","  Synthetic title  ");input.put("phone"," \t"+phone+" \t");long id=data(browser.post("/members",input),201).path("memberId").asLong();
        assertThat(jdbc.queryForObject("SELECT title='Synthetic title' AND phone=? FROM public.member WHERE member_id=?",Boolean.class,phone,id)).isTrue();
    }
    @ParameterizedTest @ValueSource(strings={"sendUnknown","sendNumericEmail","sendStringOrg","sendDecimalOrg","sendZeroOrg","sendBadEmail","verifyUnknown","verifyNumericCode","verifyBadCode",
            "signupUnknown","signupNumericPassword","signupBlankToken","signupLongToken","signupBadPassword","signupLongName","signupLongTitle","signupBlankPhone","signupWhitespacePhone","signupBadPhone"})
    void invalidJsonAndValuesAreRejectedWithoutWriting(String scenario) throws Exception {
        String email=email();String path;Map<String,Object> input;String expected="VALIDATION_ERROR";
        if(scenario.startsWith("send")) {path=SEND;input=new HashMap<>(Map.of("orgId",org,"email",email));}
        else if(scenario.startsWith("verify")) {path=VERIFY;input=new HashMap<>(Map.of("email",email,"code",secrets.code()));}
        else {path="/members";input=signup(email,secrets.proof());}
        switch(scenario) {
            case "sendUnknown","verifyUnknown","signupUnknown" -> {input.put("unknown",true);expected="INVALID_JSON";}
            case "sendNumericEmail" -> {input.put("email",123);expected="INVALID_JSON";}
            case "sendStringOrg" -> {input.put("orgId",Long.toString(org));expected="INVALID_JSON";}
            case "sendDecimalOrg" -> {input.put("orgId",1.5);expected="INVALID_JSON";}
            case "sendZeroOrg" -> input.put("orgId",0);
            case "sendBadEmail" -> input.put("email",UUID.randomUUID().toString());
            case "verifyNumericCode" -> {input.put("code",new java.security.SecureRandom().nextInt(1_000_000));expected="INVALID_JSON";}
            case "verifyBadCode" -> input.put("code",UUID.randomUUID().toString());
            case "signupNumericPassword" -> {input.put("password",new java.security.SecureRandom().nextLong());expected="INVALID_JSON";}
            case "signupBlankToken" -> input.put("verificationToken"," ");
            case "signupLongToken" -> input.put("verificationToken",UUID.randomUUID().toString().repeat(8));
            case "signupBadPassword" -> input.put("password","a".repeat(9));
            case "signupLongName" -> input.put("name","😀".repeat(101));
            case "signupLongTitle" -> input.put("title","😀".repeat(101));
            case "signupBlankPhone" -> input.put("phone","");
            case "signupWhitespacePhone" -> input.put("phone"," \t ");
            case "signupBadPhone" -> input.put("phone",UUID.randomUUID().toString());
            default -> throw new IllegalStateException("Synthetic validation scenario missing");
        }
        var hashes=countHashes(new AtomicBoolean());var response=browser.post(path,input);error(response,400,expected);
        if(expected.equals("VALIDATION_ERROR")) {
            String field=switch(scenario) {
                case "sendZeroOrg" -> "orgId";
                case "sendBadEmail" -> "email";
                case "verifyBadCode" -> "code";
                case "signupBlankToken","signupLongToken" -> "verificationToken";
                case "signupBadPassword" -> "password";
                case "signupLongName" -> "name";
                case "signupLongTitle" -> "title";
                default -> "phone";
            };
            assertField(response,field);
        }
        assertThat(hashes.get()).isZero();assertThat(memberCount(email)).isZero();assertThat(repository.verification(email,false).isEmpty()).isTrue();
        assertThat(inbox.ids(Set.of(email)).isEmpty()).isTrue();
    }
    @ParameterizedTest @ValueSource(strings={SEND,VERIFY,"/members"})
    void everyPublicMutationStillRequiresCsrf(String path) throws Exception {
        error(new Browser().withoutCsrf(path,Map.of()),403,"CSRF_INVALID");
    }
    private static String encode(String value) {return URLEncoder.encode(value,java.nio.charset.StandardCharsets.UTF_8);}
    private JsonNode data(HttpResponse<String> response,int status) {
        assertThat(response.statusCode()).isEqualTo(status);var node=body(response);assertThat(node.path("success").asBoolean()).isTrue();return node.path("data");
    }
    private void error(HttpResponse<String> response,int status,String code) {
        assertThat(response.statusCode()).isEqualTo(status);assertThat(body(response).path("error").path("code").asText()).isEqualTo(code);
    }
    private void assertField(HttpResponse<String> response,String field) {
        assertThat(body(response).path("error").path("fieldErrors").valueStream().anyMatch(f->f.path("field").asText().equals(field))).isTrue();
    }
    private JsonNode body(HttpResponse<String> response) {
        assertThat(response.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");
        var node=json.readTree(response.body());String id=response.headers().firstValue("X-Request-Id").orElseThrow();UUID.fromString(id);
        assertThat(node.path("meta").path("requestId").asText()).isEqualTo(id);return node;
    }
    private class Browser {
        private final CookieManager cookies=new CookieManager(null,CookiePolicy.ACCEPT_ALL);
        private final HttpClient http=HttpClient.newBuilder().cookieHandler(cookies).build();
        HttpResponse<String> get(String path) throws Exception {return execute("GET",path,null,null);}
        HttpResponse<String> post(String path,Object content) throws Exception {
            assertThat(get("/auth/csrf").statusCode()).isEqualTo(204);
            String token=cookies.getCookieStore().getCookies().stream().filter(c->c.getName().equals("XSRF-TOKEN")).findFirst().orElseThrow().getValue();
            return execute("POST",path,content,token);
        }
        HttpResponse<String> withoutCsrf(String path,Object content) throws Exception {return execute("POST",path,content,null);}
        private HttpResponse<String> execute(String method,String path,Object content,String csrf) throws Exception {
            var request=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api"+path)).timeout(Duration.ofSeconds(12));
            if(csrf!=null) request.header("X-XSRF-TOKEN",csrf);
            if(content!=null) request.header("Content-Type","application/json");
            return http.send(request.method(method,content==null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(json.writeValueAsString(content))).build(),HttpResponse.BodyHandlers.ofString());
        }
    }
}
