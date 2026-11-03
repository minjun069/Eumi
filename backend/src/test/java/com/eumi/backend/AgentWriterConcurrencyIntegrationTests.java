package com.eumi.backend;

import java.sql.Connection;
import java.sql.SQLException;
import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.sql.DataSource;
import com.eumi.backend.agent.AgentMessageWriter;
import com.eumi.backend.agent.AgentRepository;
import com.eumi.backend.support.AgentHttpSupport;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.CannotAcquireLockException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.times;

/** 실제 독립 JDBC 연결로 AI의 직접 INSERT를 재현한다. 공용 설정·시퀀스를 변경하지 않는다. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class AgentWriterConcurrencyIntegrationTests extends AgentHttpSupport {
    @Autowired DataSource dataSource;
    @Autowired AgentMessageWriter writer;
    @MockitoSpyBean AgentRepository repository;

    @Test
    void oldForUpdateOrderCanDeadlockWithDirectAiTerminalInsert() throws Exception {
        UUID id = pendingConversation(0);
        long questionId = pendingQuestion(id);
        try (var be = connection(); var ai = connection()) {
            try (var lock = be.prepareStatement("SELECT conversation_id FROM ai_conversation WHERE conversation_id = ? FOR UPDATE")) {
                lock.setObject(1, id); lock.executeQuery().close();
            }
            int aiPid;
            try (var statement = ai.createStatement(); var rs = statement.executeQuery("SELECT pg_backend_pid()")) {
                rs.next(); aiPid = rs.getInt(1);
            }
            var aiResult = CompletableFuture.supplyAsync(() -> terminal(ai, id, questionId, "완료"));
            awaitLockWait(aiPid);
            String beResult = terminal(be, id, questionId, "취소");
            assertThat(java.util.List.of(beResult, aiResult.get(12, TimeUnit.SECONDS)))
                    .containsExactlyInAnyOrder("40P01", "COMMITTED");
        }
        assertOneTerminal(questionId);
    }

    @Test
    void keyShareAllowsAiCommitAndWriterTreatsTheLosingTerminalAsAlreadyEnded() throws Exception {
        UUID id = pendingConversation(0);
        long questionId = pendingQuestion(id);
        var writerAtInsert = new CountDownLatch(1);
        var aiFinished = new CountDownLatch(1);
        doAnswer(call -> {
            writerAtInsert.countDown();
            assertThat(aiFinished.await(5, TimeUnit.SECONDS)).isTrue();
            return call.callRealMethod();
        }).when(repository).insertAi(eq(id), eq(questionId), eq("취소"), isNull(), isNull());
        var result = CompletableFuture.supplyAsync(() -> writer.append(id, questionId, "취소", null, null));
        try {
            assertThat(writerAtInsert.await(5, TimeUnit.SECONDS)).isTrue();
            try (var ai = connection()) {
                assertThat(terminal(ai, id, questionId, "완료")).isEqualTo("COMMITTED");
            }
        } finally { aiFinished.countDown(); }
        assertThat(result.get(8, TimeUnit.SECONDS)).isFalse();
        assertOneTerminal(questionId);
        assertThat(jdbc.queryForObject("SELECT status FROM ai_message WHERE question_id = ?", String.class, questionId)).isEqualTo("완료");
    }

    @Test
    void deadlockSignalAfterOtherTerminalCommitIsTreatedAsAlreadyEnded() {
        UUID id = pendingConversation(0);
        long questionId = pendingQuestion(id);
        doAnswer(call -> {
            try (var ai = connection()) {
                assertThat(terminal(ai, id, questionId, "완료")).isEqualTo("COMMITTED");
            }
            throw new CannotAcquireLockException("synthetic diagnostic must stay private", new SQLException("synthetic", "40P01"));
        }).when(repository).insertAi(eq(id), eq(questionId), eq("취소"), isNull(), isNull());
        assertThat(writer.append(id, questionId, "취소", null, null)).isFalse();
        assertOneTerminal(questionId);
    }

    @Test
    void deadlockWithoutExistingTerminalRetriesInANewTransactionOnce() {
        UUID id = pendingConversation(0);
        long questionId = pendingQuestion(id);
        var first = new AtomicBoolean(true);
        doAnswer(call -> {
            if (first.getAndSet(false)) throw new CannotAcquireLockException("synthetic", new SQLException("synthetic", "40P01"));
            return call.callRealMethod();
        }).when(repository).insertAi(eq(id), eq(questionId), eq("실패"), isNull(), isNull());
        assertThat(writer.append(id, questionId, "실패", null, null)).isTrue();
        assertOneTerminal(questionId);
    }

    @Test
    void unrelatedUniqueViolationIsNotSilentlyIgnored() {
        UUID id = pendingConversation(0);
        long questionId = pendingQuestion(id);
        doThrow(new DataIntegrityViolationException("synthetic", new SQLException("synthetic", "23505")))
                .when(repository).insertAi(eq(id), eq(questionId), eq("실패"), isNull(), isNull());
        assertThatThrownBy(() -> writer.append(id, questionId, "실패", null, null))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void repeatedDeadlockIsRethrownAfterExactlyOneRetry() {
        UUID id = pendingConversation(0);
        long questionId = pendingQuestion(id);
        doThrow(new CannotAcquireLockException("synthetic", new SQLException("synthetic", "40P01")))
                .when(repository).insertAi(eq(id), eq(questionId), eq("실패"), isNull(), isNull());
        assertThatThrownBy(() -> writer.append(id, questionId, "실패", null, null)).isInstanceOf(CannotAcquireLockException.class);
        verify(repository, times(2)).insertAi(id, questionId, "실패", null, null);
    }

    private Connection connection() throws SQLException {
        var connection = dataSource.getConnection();
        connection.setAutoCommit(false);
        try (var settings = connection.createStatement()) {
            settings.execute("SET LOCAL statement_timeout = '8s'");
        }
        return connection;
    }

    private String terminal(Connection connection, UUID id, long questionId, String status) {
        try (var statement = connection.prepareStatement("INSERT INTO ai_message(conversation_id, question_id, role, status, content) "
                + "VALUES (?, ?, 'AI', ?, ?)")) {
            statement.setObject(1, id); statement.setLong(2, questionId); statement.setString(3, status);
            statement.setString(4, status.equals("완료") ? "교착 회귀 검사" : null);
            statement.executeUpdate(); connection.commit(); return "COMMITTED";
        } catch (SQLException ex) {
            try { connection.rollback(); } catch (SQLException ignored) { }
            return ex.getSQLState();
        }
    }

    private void awaitLockWait(int pid) throws Exception {
        long deadline = System.nanoTime() + Duration.ofSeconds(5).toNanos();
        do {
            if (Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid = ? "
                    + "AND wait_event_type = 'Lock')", Boolean.class, pid))) return;
            Thread.sleep(10);
        } while (System.nanoTime() < deadline);
        throw new AssertionError("Direct AI insert did not reach the expected database lock wait.");
    }

    private void assertOneTerminal(long questionId) {
        assertThat(jdbc.queryForObject("SELECT count(*) FROM ai_message WHERE question_id = ? "
                + "AND status IN ('완료','실패','취소')", Integer.class, questionId)).isEqualTo(1);
    }
}
