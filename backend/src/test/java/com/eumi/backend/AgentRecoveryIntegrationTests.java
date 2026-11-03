package com.eumi.backend;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import com.eumi.backend.agent.AgentClient;
import com.eumi.backend.agent.AiMessage;
import com.eumi.backend.agent.AgentMessageWriter;
import com.eumi.backend.support.AgentHttpSupport;
import jakarta.persistence.EntityManager;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** DB·인증·HTTP는 실제 사용, AI 통신 장애만 mock으로 주입한다. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "eumi.ai.execution-limit=10s", "eumi.ai.grace-period=2s", "eumi.ai.unresponsive-after=30ms", "eumi.ai.cancel-wait=120ms"})
@ExtendWith(OutputCaptureExtension.class)
class AgentRecoveryIntegrationTests extends AgentHttpSupport {
    @MockitoBean AgentClient client;
    @Autowired EntityManager entities;
    @MockitoSpyBean AgentMessageWriter writer;

    @Test
    void recoveryWriteFailureDoesNotHideReadableMessagesOrLogExceptionText(CapturedOutput output) throws Exception {
        UUID id = pendingConversation(20000);
        long questionId = pendingQuestion(id);
        doThrow(new DataAccessResourceFailureException("synthetic-sensitive-write-detail"))
                .when(writer).append(id, questionId, "실패", null, null);
        var response = browser.get(messagesPath(id));
        assertThat(response.statusCode()).isEqualTo(200);
        assertThat(body(response).path("data").path("messages").size()).isEqualTo(1);
        assertThat(response.body()).doesNotContain("synthetic-sensitive-write-detail");
        assertThat(output.getOut()).contains("operation=recover", "exceptionType=DataAccessResourceFailureException")
                .doesNotContain("synthetic-sensitive-write-detail");
    }

    @Test
    void artifactsAreReturnedAsJsonAndMappedAsJsonbWithoutChangingTheirShape() throws Exception {
        UUID id = pendingConversation(0);
        long questionId = pendingQuestion(id);
        String artifacts = "{\"kind\":\"table\",\"rows\":[{\"region\":\"강남구\",\"value\":3}]}";
        long messageId = jdbc.queryForObject("INSERT INTO ai_message(conversation_id, question_id, role, status, content, artifacts) "
                + "VALUES (?, ?, 'AI', '완료', '시각화 검사', ?::jsonb) RETURNING message_id", Long.class, id, questionId, artifacts);
        var rows = body(browser.get(messagesPath(id))).path("data").path("messages");
        assertThat(rows.get(1).path("artifacts")).isEqualTo(json.readTree(artifacts));
        assertThat(json.readTree(entities.find(AiMessage.class, messageId).getArtifacts())).isEqualTo(json.readTree(artifacts));
    }

    @Test
    void immediateStartFailureOccursAfterCommitAndCreatesFailureMessage() throws Exception {
        doAnswer(call -> {
            assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
            assertThat(TransactionSynchronizationManager.hasResource(jdbc.getDataSource())).isFalse();
            UUID id = call.getArgument(0);
            long questionId = call.getArgument(1);
            assertThat(jdbc.queryForObject("SELECT count(*) FROM ai_message WHERE conversation_id = ? AND message_id = ?",
                    Integer.class, id, questionId)).isEqualTo(1);
            throw new AgentClient.Unavailable();
        }).when(client).start(any(), anyLong());
        var response = browser.post("/agent/questions", question(null, "실행 호출 실패 검사"));
        assertThat(response.statusCode()).isEqualTo(202);
        assertThat(awaitEnd(conversation(body(response))).path("status").asText()).isEqualTo("실패");
    }

    @Test
    void silentNonRunningQuestionIsRestartedOnlyOnce() throws Exception {
        UUID id = pendingConversation(1000);
        long questionId = pendingQuestion(id);
        when(client.status(id)).thenReturn(new AgentClient.RunStatus(false, null));
        for (int i = 0; i < 3; i++) assertThat(browser.get(messagesPath(id)).statusCode()).isEqualTo(200);
        verify(client, times(1)).start(id, questionId);
    }

    @Test
    void runningQuestionIsNotRestarted() throws Exception {
        UUID id = pendingConversation(1000);
        when(client.status(id)).thenReturn(new AgentClient.RunStatus(true, pendingQuestion(id)));
        assertThat(browser.get(messagesPath(id)).statusCode()).isEqualTo(200);
        verify(client, never()).start(any(), anyLong());
    }

    @Test
    void absoluteDeadlineCreatesFailureEvenIfNoAiResponse(CapturedOutput output) throws Exception {
        UUID id = pendingConversation(20000);
        assertThat(awaitEnd(id).path("status").asText()).isEqualTo("실패");
        awaitLog(output, "operation=execution-timeout");
        assertThat(output.getOut()).contains("AI terminal message substituted", "status=실패");
        verify(client, never()).start(any(), anyLong());
    }

    @Test
    void cancelFailureCreatesCancellationImmediately() throws Exception {
        UUID id = pendingConversation(0);
        doThrow(new AgentClient.Unavailable()).when(client).cancel(id);
        assertThat(browser.post(cancelPath(id), null).statusCode()).isEqualTo(204);
        assertThat(awaitEnd(id).path("status").asText()).isEqualTo("취소");
        assertThat(browser.post(cancelPath(id), null).statusCode()).isEqualTo(204);
        verify(client, times(1)).cancel(id);
    }

    @Test
    void missingCancelResponseFallsBackWithoutRestartingQuestion(CapturedOutput output) throws Exception {
        UUID id = pendingConversation(1000);
        assertThat(browser.post(cancelPath(id), null).statusCode()).isEqualTo(204);
        assertThat(awaitEnd(id).path("status").asText()).isEqualTo("취소");
        awaitLog(output, "operation=cancel-fallback");
        assertThat(output.getOut()).contains("AI terminal message substituted", "status=취소");
        verify(client, never()).start(any(), anyLong());
    }

    @Test
    void simultaneousQuestionsOnSameConversationAllowOnlyOneActiveQuestion() throws Exception {
        UUID id = UUID.randomUUID();
        jdbc.update("INSERT INTO ai_conversation(conversation_id, member_id) VALUES (?, ?)", id, memberId);
        browser.get("/auth/csrf");
        var calls = java.util.stream.IntStream.range(0, 2).mapToObj(index -> CompletableFuture.supplyAsync(() -> {
            try { return browser.post("/agent/questions", question(id, "경합 검사 " + index)).statusCode(); }
            catch (Exception ex) { throw new CompletionException(ex); }
        })).toList();
        List<Integer> statuses = calls.stream().map(CompletableFuture::join).sorted().toList();
        assertThat(statuses).containsExactly(202, 409);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM ai_message WHERE conversation_id = ? AND status = '질문'",
                Integer.class, id)).isEqualTo(1);
    }

    private void awaitLog(CapturedOutput output, String marker) throws Exception {
        for (int attempt = 0; attempt < 100 && !output.getOut().contains(marker); attempt++) Thread.sleep(10);
        assertThat(output.getOut()).contains(marker);
    }
}
