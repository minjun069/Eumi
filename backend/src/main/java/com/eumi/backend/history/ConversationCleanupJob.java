package com.eumi.backend.history;

import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import com.eumi.backend.agent.AgentLifecycle;
import com.eumi.backend.agent.AgentRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

@Component
public class ConversationCleanupJob {
    private static final Logger log=LoggerFactory.getLogger(ConversationCleanupJob.class);
    private static final ZoneId SEOUL=ZoneId.of("Asia/Seoul");
    private final ConversationCleanupRepository repository;
    private final AgentRepository messages;
    private final AgentLifecycle lifecycle;
    private final Clock clock;
    private final TransactionTemplate transaction;
    private final AtomicBoolean running=new AtomicBoolean();

    public ConversationCleanupJob(ConversationCleanupRepository repository,AgentRepository messages,
            AgentLifecycle lifecycle,Clock clock,PlatformTransactionManager manager) {
        this.repository=repository;this.messages=messages;this.lifecycle=lifecycle;this.clock=clock;
        transaction=new TransactionTemplate(manager);
        transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        transaction.setTimeout(5);
    }
    public record Result(UUID runId,LocalDate today,long deleted,long skipped,long failed,long elapsedMs) { }

    /** 겹친 호출은 실행하지 않는다. 취소는 DB 연결 밖, 삭제와 만료일 복원은 각각 짧은 트랜잭션이다. */
    public Optional<Result> run() {
        if(!running.compareAndSet(false,true)) {
            log.info("Conversation cleanup skipped runId={} reason=already-running",UUID.randomUUID());
            return Optional.empty();
        }
        try {
            UUID runId=UUID.randomUUID();LocalDate today=LocalDate.now(clock.withZone(SEOUL));
            long started=System.nanoTime(),deleted=0,skipped=0,failed=0,elapsed;
            UUID after=null;
            try {
                while(true) {
                    List<ConversationCleanupRepository.Candidate> batch;
                    try { batch=repository.findExpired(today,after); }
                    catch(RuntimeException ex) {
                        failed++;
                        log.warn("Conversation cleanup scan failed runId={} error={}",runId,ex.getClass().getSimpleName());
                        break;
                    }
                    if(batch.isEmpty()) break;
                    for(var candidate:batch) {
                        // 실패나 만료일 복원 여부와 무관하게 커서를 전진시켜 이번 실행에서 재방문하지 않는다.
                        UUID id=candidate.conversationId();after=id;
                        boolean cancelled=false;
                        try {
                            if(messages.activeQuestion(id).isPresent()) {
                                cancelled=true;lifecycle.cancel(id);
                            }
                            boolean force=cancelled;
                            int rows=transaction.execute(tx->force ? repository.deleteCancelled(id) : repository.deleteExpired(id,today));
                            if(rows==0) skipped++;else deleted++;
                        } catch(RuntimeException ex) {
                            failed++;
                            RuntimeException failure=ex;
                            if(cancelled) {
                                // 취소 끝 행이 늘린 기한을 복원해야 다음 실행에서도 만료 대상으로 읽힌다.
                                try { transaction.executeWithoutResult(tx->repository.restoreExpiry(candidate)); }
                                catch(RuntimeException restoreFailure) { failure=restoreFailure; }
                            }
                            log.warn("Conversation cleanup failed runId={} conversationId={} error={}",runId,id,failure.getClass().getSimpleName());
                        }
                    }
                }
            } finally {
                elapsed=Math.max(0,(System.nanoTime()-started)/1_000_000);
                log.info("Conversation cleanup runId={} today={} deleted={} skipped={} failed={} elapsedMs={}",
                        runId,today,deleted,skipped,failed,elapsed);
            }
            return Optional.of(new Result(runId,today,deleted,skipped,failed,elapsed));
        } finally { running.set(false); }
    }
}
