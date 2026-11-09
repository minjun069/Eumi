package com.eumi.backend.agent;

import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "eumi.ai", name = "mode", havingValue = "fake", matchIfMissing = true)
public class FakeAgentClient implements AgentClient {
    private static final String[][] STEPS = {{"질문 이해", "질문에서 필요한 정보를 확인합니다."},
            {"자료 확인", "답변에 필요한 자료를 확인합니다."}, {"답변 정리", "확인한 내용을 정리합니다."}};
    private final ConcurrentHashMap<UUID, Run> runs = new ConcurrentHashMap<>();
    private final AgentMessageWriter writer;
    private final AgentProperties properties;
    private final ScheduledExecutorService scheduler;
    private final Clock clock;

    private static class Run {
        final long questionId;
        final Instant startedAt;
        final AtomicBoolean finished = new AtomicBoolean();
        volatile ScheduledFuture<?> future;
        int step;
        Run(long questionId, Instant startedAt) { this.questionId = questionId; this.startedAt = startedAt; }
    }

    public FakeAgentClient(AgentMessageWriter writer, AgentProperties properties, ScheduledExecutorService scheduler, Clock clock) {
        this.writer = writer; this.properties = properties; this.scheduler = scheduler; this.clock = clock;
    }

    @Override
    public void start(UUID id, long questionId, AgentDtos.ScreenContext context) {
        var run = new Run(questionId, clock.instant());
        var existing = runs.putIfAbsent(id, run);
        if (existing != null) {
            if (existing.questionId == questionId) return;
            if (!existing.finished.get()) throw new Unavailable();
            if (!runs.replace(id, existing, run)) throw new Unavailable();
        }
        schedule(id, run);
    }

    private void schedule(UUID id, Run run) {
        run.future = scheduler.schedule(() -> advance(id, run), properties.getFakeStepDelay().toMillis(), TimeUnit.MILLISECONDS);
    }

    private void advance(UUID id, Run run) {
        if (run.finished.get()) return;
        try {
            boolean accepted;
            if (!clock.instant().isBefore(run.startedAt.plus(properties.getExecutionLimit()))) {
                run.finished.set(true);
                accepted = writer.append(id, run.questionId, "실패", null, null);
            } else if (run.step < STEPS.length) {
                var step = STEPS[run.step++];
                accepted = writer.append(id, run.questionId, "진행", step[0], step[1]);
            } else {
                run.finished.set(true);
                accepted = writer.append(id, run.questionId, "완료",
                        "AI 패널 연결을 확인했습니다. 실제 분석 결과는 AI 서비스 연결 후 제공됩니다.", null);
            }
            if (!accepted) run.finished.set(true);
            if (!run.finished.get()) schedule(id, run);
        } catch (RuntimeException ex) {
            AgentDiagnostics.failure(id, "fake-advance", ex);
            run.finished.set(true);
            try { writer.append(id, run.questionId, "실패", null, null); }
            catch (RuntimeException failure) {
                AgentDiagnostics.failure(id, "fake-failure-write", failure);
                // DB 복구 후 조회의 절대 시간 제한으로 마무리한다.
            }
        } finally {
            if (run.finished.get()) runs.remove(id, run);
        }
    }

    @Override
    public void cancel(UUID id) {
        var run = runs.get(id);
        if (run == null || !run.finished.compareAndSet(false, true)) return;
        if (run.future != null) run.future.cancel(false);
        try { writer.append(id, run.questionId, "취소", null, null); }
        finally { runs.remove(id, run); }
    }

    public boolean isRunning(UUID id) {
        var run = runs.get(id);
        return run != null && !run.finished.get();
    }
}
