package com.eumi.backend;

import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import com.eumi.backend.agent.*;
import com.eumi.backend.history.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(OutputCaptureExtension.class)
class ConversationCleanupJobTests {
    private final ConversationCleanupRepository repository=mock(ConversationCleanupRepository.class);
    private final AgentRepository messages=mock(AgentRepository.class);
    private final AgentLifecycle lifecycle=mock(AgentLifecycle.class);
    private final PlatformTransactionManager manager=mock(PlatformTransactionManager.class);
    private final Clock clock=Clock.fixed(Instant.parse("2026-11-10T15:30:00Z"),ZoneOffset.UTC);
    private final LocalDate today=LocalDate.of(2026,11,11);
    private final ConversationCleanupJob job=new ConversationCleanupJob(repository,messages,lifecycle,clock,manager);

    ConversationCleanupJobTests() {
        when(manager.getTransaction(any())).thenAnswer(call->new SimpleTransactionStatus());
        when(messages.activeQuestion(any())).thenReturn(Optional.empty());
    }
    @Test void emptyRunUsesSeoulDateAndEmitsOneSafeSummary(CapturedOutput output) {
        when(repository.findExpired(today,null)).thenReturn(List.of());
        var result=job.run().orElseThrow();
        assertThat(result.today()).isEqualTo(today);assertThat(result.deleted()+result.skipped()+result.failed()).isZero();
        verify(repository).findExpired(today,null);
        assertThat(output.getAll().contains("Conversation cleanup runId="+result.runId()+" today=2026-11-11 deleted=0 skipped=0 failed=0 elapsedMs=")).isTrue();
    }
    @Test void failedConversationIsNotReadAgainAndLaterTargetsContinue() {
        UUID first=UUID.randomUUID(),second=UUID.randomUUID();
        when(repository.findExpired(today,null)).thenReturn(List.of(candidate(first),candidate(second)));
        when(repository.findExpired(today,second)).thenReturn(List.of());
        doThrow(new IllegalStateException("Synthetic sensitive detail")).when(repository).deleteExpired(first,today);
        when(repository.deleteExpired(second,today)).thenReturn(1);
        var result=job.run().orElseThrow();assertThat(result.deleted()).isEqualTo(1);assertThat(result.failed()).isEqualTo(1);
        verify(repository,times(1)).deleteExpired(first,today);verify(repository).findExpired(today,second);
    }
    @Test void cancelledTargetRestoresExpiryAfterDeleteFailureWithoutLoggingExceptionText(CapturedOutput output) {
        UUID id=UUID.randomUUID();var candidate=candidate(id);
        when(repository.findExpired(today,null)).thenReturn(List.of(candidate));when(repository.findExpired(today,id)).thenReturn(List.of());
        when(messages.activeQuestion(id)).thenReturn(Optional.of(new AgentDtos.ActiveQuestion(1,clock.instant(),clock.instant())));
        doThrow(new IllegalStateException("Synthetic sensitive detail")).when(repository).deleteCancelled(id);
        var result=job.run().orElseThrow();assertThat(result.failed()).isEqualTo(1);
        var order=inOrder(lifecycle,repository);order.verify(lifecycle).cancel(id);order.verify(repository).deleteCancelled(id);order.verify(repository).restoreExpiry(candidate);
        assertThat(output.getAll().contains("Synthetic sensitive detail")).isFalse();
        assertThat(output.getAll().contains("conversationId="+id+" error=IllegalStateException")).isTrue();
    }
    @Test void partialCancellationFailureAlsoRestoresExpiry() {
        UUID id=UUID.randomUUID();var candidate=candidate(id);
        when(repository.findExpired(today,null)).thenReturn(List.of(candidate));when(repository.findExpired(today,id)).thenReturn(List.of());
        when(messages.activeQuestion(id)).thenReturn(Optional.of(new AgentDtos.ActiveQuestion(1,clock.instant(),clock.instant())));
        doThrow(new IllegalStateException()).when(lifecycle).cancel(id);
        assertThat(job.run().orElseThrow().failed()).isEqualTo(1);
        verify(repository).restoreExpiry(candidate);verify(repository,never()).deleteCancelled(id);
    }
    @Test void restorationFailureStillContinuesToLaterTargets(CapturedOutput output) {
        UUID first=UUID.randomUUID(),second=UUID.randomUUID();
        when(repository.findExpired(today,null)).thenReturn(List.of(candidate(first),candidate(second)));
        when(repository.findExpired(today,second)).thenReturn(List.of());
        when(messages.activeQuestion(first)).thenReturn(Optional.of(new AgentDtos.ActiveQuestion(1,clock.instant(),clock.instant())));
        doThrow(new IllegalArgumentException("Synthetic delete detail")).when(repository).deleteCancelled(first);
        doThrow(new UnsupportedOperationException("Synthetic restore detail")).when(repository).restoreExpiry(candidate(first));
        when(repository.deleteExpired(second,today)).thenReturn(1);
        var result=job.run().orElseThrow();assertThat(result.failed()).isEqualTo(1);assertThat(result.deleted()).isEqualTo(1);
        assertThat(output.getAll().contains("error=UnsupportedOperationException")).isTrue();
        assertThat(output.getAll().contains("Synthetic restore detail") || output.getAll().contains("Synthetic delete detail")).isFalse();
    }
    @Test void scanFailureLogsOnlyItsTypeAndDoesNotLeaveTheJobRunning(CapturedOutput output) {
        when(repository.findExpired(today,null)).thenThrow(new IllegalStateException("Synthetic scan detail")).thenReturn(List.of());
        assertThat(job.run().orElseThrow().failed()).isEqualTo(1);
        assertThat(job.run().orElseThrow().failed()).isZero();
        assertThat(output.getAll().contains("Conversation cleanup scan failed runId=")).isTrue();
        assertThat(output.getAll().contains("Synthetic scan detail")).isFalse();
    }
    @Test void overlappingInvocationIsSkippedAndACompletedRunCanBeStartedAgain(CapturedOutput output) throws Exception {
        var entered=new CountDownLatch(1);var release=new CountDownLatch(1);
        when(repository.findExpired(today,null)).thenAnswer(call->{
            entered.countDown();if(!release.await(5,TimeUnit.SECONDS)) throw new IllegalStateException("Synthetic gate timeout");return List.of();
        });
        try(var executor=Executors.newSingleThreadExecutor()) {
            var first=executor.submit(job::run);
            try {assertThat(entered.await(3,TimeUnit.SECONDS)).isTrue();assertThat(job.run()).isEmpty();}
            finally {release.countDown();}
            assertThat(first.get(5,TimeUnit.SECONDS)).isPresent();assertThat(job.run()).isPresent();
        }
        assertThat(output.getAll().lines().filter(line->line.matches(".*Conversation cleanup skipped runId=[0-9a-f-]{36} reason=already-running")).count()).isEqualTo(1);
    }
    private ConversationCleanupRepository.Candidate candidate(UUID id) {return new ConversationCleanupRepository.Candidate(id,today);}
}
