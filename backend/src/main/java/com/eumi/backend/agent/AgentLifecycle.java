package com.eumi.backend.agent;

import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;
import java.util.stream.IntStream;
import org.springframework.stereotype.Component;

/** DB 트랜잭션 밖에서 AI를 호출한다. 단일 BE 프로세스에서 복구 재요청을 질문당 한 번으로 제한한다. */
@Component
public class AgentLifecycle {
    private final AgentRepository repository;
    private final AgentMessageWriter writer;
    private final AgentClient client;
    private final AgentProperties properties;
    private final ScheduledExecutorService scheduler;
    private final Clock clock;
    private final ReentrantLock[] locks = IntStream.range(0, 64).mapToObj(i -> new ReentrantLock()).toArray(ReentrantLock[]::new);
    private final ConcurrentHashMap<Long, Attempt> attempts = new ConcurrentHashMap<>();

    private static class Attempt {
        boolean retried;
        volatile boolean cancelling;
        Instant cancelDeadline;
        final Instant expiresAt;
        Attempt(Instant expiresAt) { this.expiresAt = expiresAt; }
    }

    public AgentLifecycle(AgentRepository repository, AgentMessageWriter writer, AgentClient client,
            AgentProperties properties, ScheduledExecutorService scheduler, Clock clock) {
        this.repository = repository; this.writer = writer; this.client = client;
        this.properties = properties; this.scheduler = scheduler; this.clock = clock;
    }

    private ReentrantLock lock(UUID id) { return locks[Math.floorMod(id.hashCode(), locks.length)]; }

    public void start(UUID id, long questionId) {
        var lock = lock(id);
        lock.lock();
        try {
            startIfActive(id, questionId);
        } finally { lock.unlock(); }
    }

    private void startIfActive(UUID id, long questionId) {
        if (repository.activeQuestion(id).filter(q -> q.questionId() == questionId).isEmpty()) return;
        try { client.start(id, questionId); }
        catch (AgentClient.Unavailable ex) {
            AgentDiagnostics.failure(id, "start", ex);
            appendSubstitute(id, questionId, "실패", "start-failure");
        }
    }

    private Attempt attempt(AgentDtos.ActiveQuestion question) {
        Instant now = clock.instant();
        attempts.entrySet().removeIf(entry -> !entry.getValue().cancelling && entry.getValue().expiresAt.isBefore(now));
        return attempts.computeIfAbsent(question.questionId(), id -> new Attempt(question.askedAt()
                .plus(properties.getExecutionLimit()).plus(properties.getGracePeriod()).plus(properties.getCancelWait())));
    }

    public void recover(UUID id) {
        var lock = lock(id);
        if (!lock.tryLock()) return;
        try {
            var active = repository.activeQuestion(id);
            if (active.isEmpty()) return;
            var question = active.get();
            var state = attempt(question);
            Instant now = clock.instant();
            if (state.cancelling) {
                if (!now.isBefore(state.cancelDeadline)) finishCancellation(id, question.questionId());
                return;
            }
            if (!now.isBefore(question.askedAt().plus(properties.getExecutionLimit()).plus(properties.getGracePeriod()))) {
                appendSubstitute(id, question.questionId(), "실패", "execution-timeout");
                attempts.remove(question.questionId());
                return;
            }
            if (now.isBefore(question.lastActivityAt().plus(properties.getUnresponsiveAfter()))) return;
            try {
                var status = client.status(id);
                boolean runningThisQuestion = status.running() && Long.valueOf(question.questionId()).equals(status.questionId());
                if (!runningThisQuestion && !state.retried) {
                    state.retried = true;
                    startIfActive(id, question.questionId());
                }
            } catch (AgentClient.Unavailable ex) {
                AgentDiagnostics.failure(id, "status", ex);
                // 상태 조회 장애만으로 끝내지 않고 절대 실행 제한까지 다음 조회에서 재확인한다.
            }
        } finally { lock.unlock(); }
    }

    public void cancel(UUID id) {
        var lock = lock(id);
        lock.lock();
        try {
            var active = repository.activeQuestion(id);
            if (active.isEmpty()) return;
            var question = active.get();
            var state = attempt(question);
            if (state.cancelling) return;
            state.cancelling = true;
            state.cancelDeadline = clock.instant().plus(properties.getCancelWait());
            // 완료된 뒤 새 질문이 시작돼도 이 타이머는 원래 questionId에만 적용한다.
            scheduler.schedule(() -> {
                try { finishCancellation(id, question.questionId()); }
                catch (RuntimeException ex) {
                    AgentDiagnostics.failure(id, "cancel-fallback", ex);
                    // DB 복구 후 다음 메시지 조회에서도 취소를 마무리한다.
                }
            }, properties.getCancelWait().toMillis(), TimeUnit.MILLISECONDS);
            try { client.cancel(id); }
            catch (AgentClient.Unavailable ex) {
                AgentDiagnostics.failure(id, "cancel", ex);
                finishCancellation(id, question.questionId());
            }
        } finally { lock.unlock(); }
    }

    private void finishCancellation(UUID id, long questionId) {
        appendSubstitute(id, questionId, "취소", "cancel-fallback");
        attempts.remove(questionId);
    }

    private void appendSubstitute(UUID id, long questionId, String status, String operation) {
        if (writer.append(id, questionId, status, null, null)) {
            AgentDiagnostics.substituted(id, questionId, operation, status);
        }
    }
}
