package com.eumi.backend;

import java.sql.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import com.eumi.backend.agent.*;
import com.eumi.backend.history.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.core.env.Environment;
import org.springframework.dao.CannotAcquireLockException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.scheduling.annotation.ScheduledAnnotationBeanPostProcessor;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.convention.TestBean;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** 실제 공용 DB. 후보 SQL에 테스트 회원 조건만 더해 다른 작업의 만료 대화를 건드리지 않는다. */
@Tag("local-integration")
@ActiveProfiles("local")
@ExtendWith(OutputCaptureExtension.class)
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties={"eumi.ai.mode=fake","eumi.ai.fake-step-delay=30s","spring.datasource.hikari.minimum-idle=1"})
class ConversationCleanupIntegrationTests {
    private static final LocalDate TODAY=LocalDate.of(2026,11,11);
    private static final Instant NOW=Instant.parse("2026-11-10T15:30:00Z");
    @Autowired ConversationCleanupJob job;
    @Autowired JdbcTemplate jdbc;
    @Autowired AgentMessageWriter writer;
    @Autowired FakeAgentClient fake;
    @Autowired Environment environment;
    @Autowired ScheduledAnnotationBeanPostProcessor scheduled;
    @MockitoSpyBean ConversationCleanupRepository repository;
    @MockitoSpyBean AgentRepository messages;
    @MockitoSpyBean AgentLifecycle lifecycle;
    @TestBean(methodName="fixedClock") Clock clock;
    static Clock fixedClock() {return Clock.fixed(NOW,ZoneOffset.UTC);}
    private final String marker="cleanup-"+UUID.randomUUID();
    private final String privateQuestion="Synthetic private question "+UUID.randomUUID();
    private final long uuidPrefix=UUID.randomUUID().getMostSignificantBits();
    private final List<UUID> ids=new ArrayList<>();
    private final List<Integer> pageSizes=new ArrayList<>();
    private final AtomicBoolean lookupHadTransaction=new AtomicBoolean();
    private long org,member,other;

    @BeforeEach void setup() {
        org=jdbc.queryForObject("INSERT INTO public.organization(org_name,jurisdiction_sigungu_code,official_domain) VALUES (?,'11680','eumi.test') RETURNING org_id",Long.class,marker);
        member=member();other=member();
        // 실제 SQL의 기한·UUID keyset·LIMIT 500은 유지하고, 조회 범위만 소유 fixture로 제한한다.
        var scoped=new ConversationCleanupRepository(new JdbcTemplate(jdbc.getDataSource()) {
            @Override public <T> List<T> query(String sql,RowMapper<T> mapper,Object... args) {
                String boundary="WHERE delete_scheduled_at <= ?";
                if(!sql.contains(boundary)) throw new IllegalStateException("Synthetic cleanup query scope could not be applied");
                String owned="WHERE member_id IN ("+member+","+other+") AND delete_scheduled_at <= ?";
                return super.query(sql.replace(boundary,owned),mapper,args);
            }
        });
        doAnswer(call->{
            if(TransactionSynchronizationManager.isActualTransactionActive() || TransactionSynchronizationManager.hasResource(jdbc.getDataSource())) lookupHadTransaction.set(true);
            var rows=scoped.findExpired(call.getArgument(0),call.getArgument(1));pageSizes.add(rows.size());return rows;
        }).when(repository).findExpired(any(LocalDate.class),nullable(UUID.class));
    }
    private long member() {
        return jdbc.queryForObject("INSERT INTO public.member(org_id,email_normalized,name,password_hash) VALUES (?,?,?,?) RETURNING member_id",
                Long.class,org,"cleanup-"+UUID.randomUUID()+"@eumi.test",marker,UUID.randomUUID().toString());
    }
    @AfterEach void cleanup() {
        reset(repository,messages,lifecycle);
        for(UUID id:ids) fake.cancel(id);
        jdbc.update("DELETE FROM public.ai_conversation WHERE member_id IN (?,?)",member,other);
        jdbc.update("DELETE FROM public.member WHERE org_id=? AND member_id IN (?,?)",org,member,other);
        if(org!=0) jdbc.update("DELETE FROM public.organization WHERE org_id=? AND org_name=?",org,marker);
    }
    private UUID id() {UUID id=new UUID(uuidPrefix,ids.size()+1L);ids.add(id);return id;}
    private UUID conversation(long owner,LocalDate expiry,boolean active) {
        UUID id=id();jdbc.update("INSERT INTO public.ai_conversation(conversation_id,member_id) VALUES (?,?)",id,owner);
        long question=messages.insertQuestion(id,privateQuestion);
        if(active) fake.start(id,question,null);
        else assertThat(writer.append(id,question,"완료","Synthetic answer",null)).isTrue();
        jdbc.update("UPDATE public.ai_conversation SET delete_scheduled_at=? WHERE conversation_id=?",expiry,id);return id;
    }
    private long count(String table,UUID id) {return jdbc.queryForObject("SELECT count(*) FROM public."+table+" WHERE conversation_id=?",Long.class,id);}
    private LocalDate expiry(UUID id) {return jdbc.queryForObject("SELECT delete_scheduled_at FROM public.ai_conversation WHERE conversation_id=?",LocalDate.class,id);}
    private long question(UUID id) {return jdbc.queryForObject("SELECT message_id FROM public.ai_message WHERE conversation_id=? AND status='질문'",Long.class,id);}
    private void saveAiCancellation(UUID id,long question) {
        // fake의 쓰기 허용 여부는 DB current_date를 쓴다. AI 직접 저장을 모사해 고정 Clock 검사와 분리한다.
        // fake가 이미 끝 행을 썼으면 그대로 두며, 실제 AI 서버는 호출하지 않는다.
        jdbc.update("INSERT INTO public.ai_message(conversation_id,question_id,role,status,created_at) "+
                "SELECT ?,?,'AI','취소',? WHERE NOT EXISTS "+
                "(SELECT 1 FROM public.ai_message WHERE question_id=? AND status IN ('완료','실패','취소')) ON CONFLICT DO NOTHING",
                id,question,NOW.atOffset(ZoneOffset.UTC),question);
    }
    private void cancelAndSave(UUID id) {
        long question=question(id);
        doAnswer(call->{call.callRealMethod();saveAiCancellation(id,question);return null;}).when(lifecycle).cancel(id);
    }
    private ConversationCleanupJob.Result run() {return job.run().orElseThrow();}
    private void deleted(UUID id) {assertThat(count("ai_conversation",id)).isZero();assertThat(count("ai_message",id)).isZero();}

    @Test void seoulTodayAndYesterdayAreDeletedTomorrowSurvivesAndRepeatedRunIsSafe(CapturedOutput output) {
        UUID yesterday=conversation(member,TODAY.minusDays(1),false),today=conversation(other,TODAY,false),tomorrow=conversation(member,TODAY.plusDays(1),false);
        long futureMessages=count("ai_message",tomorrow);
        var result=run();assertThat(result.today()).isEqualTo(TODAY);assertThat(result.deleted()).isEqualTo(2);
        assertThat(result.skipped()+result.failed()).isZero();deleted(yesterday);deleted(today);
        assertThat(count("ai_conversation",tomorrow)).isEqualTo(1);assertThat(count("ai_message",tomorrow)).isEqualTo(futureMessages);
        var again=run();assertThat(again.deleted()+again.skipped()+again.failed()).isZero();
        assertThat(count("ai_message",tomorrow)).isEqualTo(futureMessages);assertThat(lookupHadTransaction.get()).isFalse();
        String line="Conversation cleanup runId="+result.runId()+" today=2026-11-11 deleted=2 skipped=0 failed=0 elapsedMs=";
        assertThat(output.getAll().contains(line)).isTrue();assertThat(output.getAll().contains(privateQuestion)).isFalse();
        assertThat(output.getAll().lines().filter(s->s.contains("Conversation cleanup runId="+result.runId())).count()).isEqualTo(1);
    }
    @Test void expiredRunningFakeIsCancelledOutsideTransactionAndDeletedEvenAfterTheTriggerExtendsExpiry() {
        UUID id=conversation(member,TODAY,true);long question=question(id);
        var cancelInTransaction=new AtomicBoolean();var extended=new AtomicBoolean();var deletionInTransaction=new AtomicBoolean();
        doAnswer(call->{
            cancelInTransaction.set(TransactionSynchronizationManager.isActualTransactionActive() || TransactionSynchronizationManager.hasResource(jdbc.getDataSource()));
            call.callRealMethod();saveAiCancellation(id,question);return null;
        }).when(lifecycle).cancel(id);
        doAnswer(call->{
            extended.set(expiry(id).isAfter(TODAY));
            deletionInTransaction.set(TransactionSynchronizationManager.isActualTransactionActive() && TransactionSynchronizationManager.hasResource(jdbc.getDataSource()));
            return call.callRealMethod();
        }).when(repository).deleteCancelled(id);
        var result=run();assertThat(result.deleted()).isEqualTo(1);assertThat(result.failed()).isZero();
        assertThat(cancelInTransaction.get()).isFalse();assertThat(deletionInTransaction.get()).isTrue();assertThat(extended.get()).isTrue();
        var order=inOrder(lifecycle,repository);order.verify(lifecycle).cancel(id);order.verify(repository).deleteCancelled(id);
        verify(repository,never()).deleteExpired(eq(id),any());assertThat(fake.isRunning(id)).isFalse();deleted(id);
        assertThat(writer.append(id,question,"완료","Synthetic late answer",null)).isFalse();
        assertThatThrownBy(()->messages.insertAi(id,question,"완료","Synthetic direct late answer",null)).isInstanceOf(DataIntegrityViolationException.class);
        deleted(id);
    }
    @Test void aRealRowLockFailsOnlyThatConversationAndTheNextRunRetriesItAfterUnlock() throws Exception {
        UUID locked=conversation(member,TODAY,false),later=conversation(member,TODAY,false);
        try(var blocker=jdbc.getDataSource().getConnection();var executor=Executors.newSingleThreadExecutor()) {
            blocker.setAutoCommit(false);
            try(var statement=blocker.prepareStatement("SELECT conversation_id FROM public.ai_conversation WHERE conversation_id=? FOR UPDATE")) {
                statement.setObject(1,locked);statement.executeQuery().close();
            }
            try {
                var result=executor.submit(this::run).get(12,TimeUnit.SECONDS);
                assertThat(result.deleted()).isEqualTo(1);assertThat(result.failed()).isEqualTo(1);assertThat(result.skipped()).isZero();
                assertThat(count("ai_conversation",locked)).isEqualTo(1);deleted(later);verify(repository,times(1)).deleteExpired(locked,TODAY);
            } finally {blocker.rollback();}
        }
        var retry=run();assertThat(retry.deleted()).isEqualTo(1);assertThat(retry.failed()).isZero();deleted(locked);
    }
    @Test void cancelledDeleteFailureRestoresOriginalExpirySoTheNextRunCanRetry(CapturedOutput output) {
        UUID id=conversation(member,TODAY,true);var restoredInTransaction=new AtomicBoolean();
        cancelAndSave(id);
        doThrow(new CannotAcquireLockException("Synthetic private failure "+privateQuestion)).when(repository).deleteCancelled(id);
        doAnswer(call->{restoredInTransaction.set(TransactionSynchronizationManager.isActualTransactionActive());return call.callRealMethod();})
                .when(repository).restoreExpiry(any());
        var failed=run();assertThat(failed.failed()).isEqualTo(1);assertThat(failed.deleted()).isZero();
        assertThat(expiry(id)).isEqualTo(TODAY);assertThat(restoredInTransaction.get()).isTrue();
        assertThat(count("ai_message",id)).isEqualTo(2);assertThat(fake.isRunning(id)).isFalse();
        var retry=run();assertThat(retry.deleted()).isEqualTo(1);assertThat(retry.failed()).isZero();deleted(id);
        assertThat(output.getAll().contains(privateQuestion)).isFalse();
        assertThat(output.getAll().contains("Conversation cleanup failed runId="+failed.runId()+" conversationId="+id+" error=CannotAcquireLockException")).isTrue();
    }
    @Test void partialCancellationFailureRestoresExpiryAndCanBeRetried() {
        UUID id=conversation(member,TODAY,true);long question=question(id);
        doAnswer(call->{call.callRealMethod();saveAiCancellation(id,question);throw new IllegalStateException("Synthetic cancellation result lost");}).when(lifecycle).cancel(id);
        assertThat(run().failed()).isEqualTo(1);assertThat(expiry(id)).isEqualTo(TODAY);
        verify(repository,never()).deleteCancelled(id);
        assertThat(run().deleted()).isEqualTo(1);deleted(id);
    }
    @Test void expiryRestorationAlsoTimesOutAndTheJobContinuesWithTheNextConversation() throws Exception {
        UUID locked=conversation(member,TODAY,true),later=conversation(member,TODAY,false);
        cancelAndSave(locked);
        try(var blocker=jdbc.getDataSource().getConnection();var executor=Executors.newSingleThreadExecutor()) {
            blocker.setAutoCommit(false);
            doAnswer(call->{
                // 취소 저장 뒤 다른 트랜잭션이 잠금을 잡는 상황을 만든다. 복원 UPDATE는 실제로 대기한다.
                try(var statement=blocker.prepareStatement("SELECT conversation_id FROM public.ai_conversation WHERE conversation_id=? FOR UPDATE")) {
                    statement.setObject(1,locked);statement.executeQuery().close();
                }
                throw new CannotAcquireLockException("Synthetic delete failure before restoration");
            }).when(repository).deleteCancelled(locked);
            try {
                var result=executor.submit(this::run).get(12,TimeUnit.SECONDS);
                assertThat(result.failed()).isEqualTo(1);assertThat(result.deleted()).isEqualTo(1);
                assertThat(result.skipped()).isZero();deleted(later);
                verify(repository).restoreExpiry(new ConversationCleanupRepository.Candidate(locked,TODAY));
                assertThat(expiry(locked).isAfter(TODAY)).isTrue();
            } finally {blocker.rollback();}
        }
    }
    @Test void aCompletedQuestionThatExtendsExpiryAfterSelectionIsSkipped() {
        UUID id=conversation(member,TODAY,false);
        doAnswer(call->{
            var value=call.callRealMethod();jdbc.update("UPDATE public.ai_conversation SET delete_scheduled_at=? WHERE conversation_id=?",TODAY.plusMonths(3),id);return value;
        }).when(messages).activeQuestion(id);
        var result=run();assertThat(result.deleted()).isZero();assertThat(result.skipped()).isEqualTo(1);assertThat(result.failed()).isZero();
        assertThat(expiry(id)).isEqualTo(TODAY.plusMonths(3));assertThat(count("ai_message",id)).isEqualTo(2);
    }
    @Test void alreadyDeletedTargetIsSkippedWithoutFailure() {
        UUID id=conversation(member,TODAY,false);
        doAnswer(call->{var value=call.callRealMethod();jdbc.update("DELETE FROM public.ai_conversation WHERE conversation_id=?",id);return value;}).when(messages).activeQuestion(id);
        var result=run();assertThat(result.skipped()).isEqualTo(1);assertThat(result.failed()+result.deleted()).isZero();deleted(id);
    }
    @Test void moreThanTwoPagesAreReadByUuidKeysetAndAllMessagesAreCascaded() {
        var rows=new ArrayList<Object[]>();
        for(int i=0;i<1050;i++) rows.add(new Object[]{id(),i%2==0 ? member : other});
        jdbc.batchUpdate("INSERT INTO public.ai_conversation(conversation_id,member_id) VALUES (?,?)",rows);
        jdbc.update("INSERT INTO public.ai_message(conversation_id,role,status,content) SELECT conversation_id,'Member','질문',? FROM public.ai_conversation WHERE member_id IN (?,?)",privateQuestion,member,other);
        jdbc.update("INSERT INTO public.ai_message(conversation_id,question_id,role,status,content) SELECT conversation_id,message_id,'AI','완료','Synthetic bulk answer' FROM public.ai_message WHERE role='Member' AND conversation_id IN (SELECT conversation_id FROM public.ai_conversation WHERE member_id IN (?,?))",member,other);
        jdbc.update("UPDATE public.ai_conversation SET delete_scheduled_at=? WHERE member_id IN (?,?)",TODAY,member,other);
        var result=run();assertThat(result.deleted()).isEqualTo(1050);assertThat(result.failed()+result.skipped()).isZero();
        assertThat(pageSizes).containsExactly(500,500,50,0);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM public.ai_conversation WHERE member_id IN (?,?)",Long.class,member,other)).isZero();
        for(UUID id:ids) assertThat(count("ai_message",id)).isZero();
    }
    @Test void theSharedTestConfigurationDisablesScheduledExecution() {
        assertThat(environment.getProperty("eumi.batch.conversation-cleanup-cron")).isEqualTo("-");
        assertThat(scheduled.getScheduledTasks()).isEmpty();
    }
}
