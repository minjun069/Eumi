package com.eumi.backend;

import java.time.*;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.*;
import com.eumi.backend.agent.*;
import com.eumi.backend.common.error.ApiException;
import org.junit.jupiter.api.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentLifecycleTests {
    private final AgentRepository repository = mock(AgentRepository.class);
    private final AgentMessageWriter writer = mock(AgentMessageWriter.class);
    private final AgentClient client = mock(AgentClient.class);
    private final ScheduledExecutorService scheduler = mock(ScheduledExecutorService.class);
    private final ScheduledFuture<?> cancelTask = mock(ScheduledFuture.class);
    private final UUID id = UUID.randomUUID();
    private final Instant asked = Instant.parse("2026-11-09T00:00:00Z");
    private final MutableClock clock = new MutableClock(asked);
    private final AgentDtos.ScreenContext context = new AgentDtos.ScreenContext("1168064000", "2025-12");
    private AgentLifecycle lifecycle;

    @BeforeEach void setup() {
        var properties = new AgentProperties();
        properties.setExecutionLimit(Duration.ofSeconds(10)); properties.setGracePeriod(Duration.ofSeconds(2));
        properties.setUnresponsiveAfter(Duration.ofSeconds(1)); properties.setCancelWait(Duration.ofSeconds(3));
        lifecycle = new AgentLifecycle(repository, writer, client, properties, scheduler, clock);
        when(repository.activeQuestion(id)).thenReturn(Optional.of(new AgentDtos.ActiveQuestion(101, asked, asked)));
    }

    @Test void lostInitialAndRetryResponsesDoNotFinishBeforeAbsoluteDeadline() {
        doThrow(new AgentClient.Unavailable()).when(client).start(id, 101, context);
        lifecycle.start(id, 101, context);
        clock.now = asked.plusSeconds(2);
        for (int i = 0; i < 4; i++) lifecycle.recover(id);
        verify(client, times(2)).start(id, 101, context);
        verifyNoInteractions(writer);
        clock.now = asked.plusSeconds(12);
        lifecycle.recover(id);
        verify(writer).append(id, 101, "실패", null, null);
    }

    @Test void concurrentPollingRetriesOnceAndRestartHasNoStoredContext() throws Exception {
        clock.now = asked.plusSeconds(2);
        var calls = java.util.stream.IntStream.range(0, 12)
                .mapToObj(i -> CompletableFuture.runAsync(() -> lifecycle.recover(id))).toArray(CompletableFuture[]::new);
        CompletableFuture.allOf(calls).get(3, TimeUnit.SECONDS);
        verify(client, times(1)).start(id, 101, null);
        verifyNoInteractions(writer);
    }

    @Test void recentProgressSuppressesRetry() {
        clock.now = asked.plusSeconds(2);
        when(repository.activeQuestion(id)).thenReturn(Optional.of(new AgentDtos.ActiveQuestion(101, asked, clock.now)));
        lifecycle.recover(id);
        verifyNoInteractions(client, writer);
    }

    @Test void terminalCallbackDuringCancelDoesNotWaitForTheOutboundHttpLock() throws Exception {
        doReturn(cancelTask).when(scheduler).schedule(any(Runnable.class), anyLong(), any(TimeUnit.class));
        when(repository.notification(id, 102)).thenReturn(Optional.of(new AgentDtos.StoredNotification(101, "취소")));
        doAnswer(invocation -> {
            CompletableFuture.runAsync(() -> lifecycle.notified(id, 102)).get(1, TimeUnit.SECONDS);
            return null;
        }).when(client).cancel(id);
        lifecycle.start(id, 101, context);
        lifecycle.cancel(id);
        verify(cancelTask).cancel(false);
        verifyNoInteractions(writer);
    }

    @Test void callbackMustIdentifyAnAiRowFromThatConversation() {
        assertThatThrownBy(() -> lifecycle.notified(id, 102)).isInstanceOf(ApiException.class);
        when(repository.notification(id, 102)).thenReturn(Optional.of(new AgentDtos.StoredNotification(101, "완료")));
        lifecycle.notified(id, 102);
        lifecycle.notified(id, 102);
        verifyNoInteractions(client, writer);
    }

    private static class MutableClock extends Clock {
        Instant now;
        MutableClock(Instant value) { now = value; }
        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zone) { return this; }
        @Override public Instant instant() { return now; }
    }
}
