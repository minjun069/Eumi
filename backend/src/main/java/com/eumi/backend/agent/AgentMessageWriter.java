package com.eumi.backend.agent;

import java.sql.SQLException;
import java.util.UUID;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** AI처럼 행마다 독립 커밋한다. 끝난 질문의 늦은 행만 무시하며 다른 정합성 오류는 숨기지 않는다. */
@Component
public class AgentMessageWriter {
    private final AgentRepository repository;
    private final TransactionTemplate transaction;

    public AgentMessageWriter(AgentRepository repository, PlatformTransactionManager manager) {
        this.repository = repository;
        transaction = new TransactionTemplate(manager);
        transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public boolean append(UUID id, long questionId, String status, String content, String details) {
        return append(id, questionId, status, content, details, false);
    }

    private boolean append(UUID id, long questionId, String status, String content, String details, boolean retried) {
        try {
            return Boolean.TRUE.equals(transaction.execute(tx -> {
                if (!repository.lockWritable(id) || !repository.questionExists(id, questionId) || repository.ended(questionId)) return false;
                repository.insertAi(id, questionId, status, content, details);
                return true;
            }));
        } catch (DataAccessException ex) {
            if (ex.getMostSpecificCause() instanceof SQLException sql) {
                String state = sql.getSQLState();
                if (("23505".equals(state) || "40P01".equals(state)) && repository.ended(questionId)) return false;
                if ("23503".equals(sql.getSQLState()) && !repository.questionExists(id, questionId)) return false;
                if ("40P01".equals(state) && !retried) {
                    AgentDiagnostics.failure(id, "message-deadlock-retry", ex);
                    // 롤백이 끝난 새 트랜잭션에서 한 번 재확인한다. 다른 끝 행이 커밋 중일 수도 있다.
                    return append(id, questionId, status, content, details, true);
                }
            }
            throw ex;
        }
    }
}
