package com.eumi.backend.agent;

import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.locks.ReentrantLock;
import java.util.stream.IntStream;
import org.springframework.stereotype.Component;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;

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
        volatile ScheduledFuture<?> cancelTask;
        final Instant expiresAt;
        final UUID conversationId;
        final AgentDtos.ScreenContext context;
        Attempt(UUID conversationId, Instant expiresAt, AgentDtos.ScreenContext context) {
            this.conversationId = conversationId; this.expiresAt = expiresAt; this.context = context;
        }
    }

    public AgentLifecycle(AgentRepository repository, AgentMessageWriter writer, AgentClient client,
            AgentProperties properties, ScheduledExecutorService scheduler, Clock clock) {
        this.repository = repository; this.writer = writer; this.client = client;
        this.properties = properties; this.scheduler = scheduler; this.clock = clock;
    }

    private ReentrantLock lock(UUID id) { return locks[Math.floorMod(id.hashCode(), locks.length)]; }

    public void start(UUID id, long questionId, AgentDtos.ScreenContext context) {
        var lock = lock(id);
        lock.lock();
        try {
            var active = repository.activeQuestion(id).filter(q -> q.questionId() == questionId);
            if (active.isEmpty()) return;
            var state = attempt(id, active.get(), context);
            startIfActive(id, questionId, state.context);
        } finally { lock.unlock(); }
    }

    private void startIfActive(UUID id, long questionId, AgentDtos.ScreenContext context) {
        if (repository.activeQuestion(id).filter(q -> q.questionId() == questionId).isEmpty()) return;
        try { client.start(id, questionId, context); }
        catch (AgentClient.Unavailable ex) {
            AgentDiagnostics.failure(id, "start", ex);
            // 응답 유실이어도 AI가 실행 중일 수 있다. 재요청 1회와 절대 실행 제한으로 복구한다.
        }
    }

    private Attempt attempt(UUID conversationId, AgentDtos.ActiveQuestion question, AgentDtos.ScreenContext context) {
        Instant now = clock.instant();
        attempts.entrySet().removeIf(entry -> !entry.getValue().cancelling && entry.getValue().expiresAt.isBefore(now));
        return attempts.computeIfAbsent(question.questionId(), id -> new Attempt(conversationId, question.askedAt()
                .plus(properties.getExecutionLimit()).plus(properties.getGracePeriod()).plus(properties.getCancelWait()), context));
    }

    public void recover(UUID id) {
        var lock = lock(id);
        if (!lock.tryLock()) return;
        try {
            var active = repository.activeQuestion(id);
            if (active.isEmpty()) { clearConversation(id); return; }
            var question = active.get();
            var state = attempt(id, question, null);
            Instant now = clock.instant();
            if (state.cancelling) {
                if (!now.isBefore(state.cancelDeadline)) finishCancellation(id, question.questionId());
                return;
            }
            if (!now.isBefore(question.askedAt().plus(properties.getExecutionLimit()).plus(properties.getGracePeriod()))) {
                appendSubstitute(id, question.questionId(), "실패", "execution-timeout");
                finished(id, question.questionId());
                return;
            }
            if (now.isBefore(question.lastActivityAt().plus(properties.getUnresponsiveAfter()))) return;
            if (!state.retried) {
                state.retried = true;
                startIfActive(id, question.questionId(), state.context);
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
            var state = attempt(id, question, null);
            if (state.cancelling) return;
            state.cancelling = true;
            state.cancelDeadline = clock.instant().plus(properties.getCancelWait());
            // 완료된 뒤 새 질문이 시작돼도 이 타이머는 원래 questionId에만 적용한다.
            state.cancelTask = scheduler.schedule(() -> {
                try { finishCancellation(id, question.questionId()); }
                catch (RuntimeException ex) {
                    AgentDiagnostics.failure(id, "cancel-fallback", ex);
                    // DB 복구 후 다음 메시지 조회에서도 취소를 마무리한다.
                }
            }, properties.getCancelWait().toMillis(), TimeUnit.MILLISECONDS);
            if (attempts.get(question.questionId()) != state) state.cancelTask.cancel(false);
            try { client.cancel(id); }
            catch (AgentClient.Unavailable ex) {
                AgentDiagnostics.failure(id, "cancel", ex);
                // HTTP 실패 여부와 무관하게 이미 잡힌 취소 대기 시각까지 끝 행을 기다린다.
            }
            if (repository.ended(question.questionId())) finished(id, question.questionId());
        } finally { lock.unlock(); }
    }

    private void finishCancellation(UUID id, long questionId) {
        appendSubstitute(id, questionId, "취소", "cancel-fallback");
        finished(id, questionId);
    }

    public void notified(UUID conversationId, long messageId) {
        var row = repository.notification(conversationId, messageId).orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND));
        AgentDiagnostics.notified(conversationId, messageId, row.questionId(), row.status());
        if (java.util.Set.of("완료", "실패", "취소").contains(row.status())) finished(conversationId, row.questionId());
    }

    // AI는 INT-02 응답 전에 INT-07을 보낼 수 있다. HTTP 호출의 대화 잠금을 잡지 않아 상호 대기를 피한다.
    private void finished(UUID conversationId, long questionId) {
        var state = attempts.get(questionId);
        if (state != null && state.conversationId.equals(conversationId) && attempts.remove(questionId, state)) {
            if (state.cancelTask != null) state.cancelTask.cancel(false);
        }
    }

    private void clearConversation(UUID conversationId) {
        attempts.forEach((questionId, state) -> {
            if (state.conversationId.equals(conversationId)) finished(conversationId, questionId);
        });
    }

    private void appendSubstitute(UUID id, long questionId, String status, String operation) {
        if (writer.append(id, questionId, status, null, null)) {
            AgentDiagnostics.substituted(id, questionId, operation, status);
        }
    }
}
