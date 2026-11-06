package com.eumi.backend.agent;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.json.JsonMapper;

@Repository
public class AgentRepository {
    private final JdbcTemplate jdbc;
    private final JsonMapper json;

    public AgentRepository(JdbcTemplate jdbc, JsonMapper json) { this.jdbc = jdbc; this.json = json; }

    public void createConversation(UUID id, long memberId) {
        jdbc.update("INSERT INTO ai_conversation(conversation_id, member_id) VALUES (?, ?)", id, memberId);
    }

    public void requireOwned(UUID id, long memberId, boolean lock) {
        var rows = jdbc.queryForList("SELECT conversation_id FROM ai_conversation WHERE conversation_id = ? "
                + "AND member_id = ? AND delete_scheduled_at > current_date" + (lock ? " FOR UPDATE" : ""), id, memberId);
        if (rows.isEmpty()) throw new ApiException(ErrorCode.NOT_FOUND);
    }

    public boolean lockWritable(UUID id) {
        return !jdbc.queryForList("SELECT c.conversation_id FROM ai_conversation c JOIN member m ON m.member_id = c.member_id "
                + "WHERE c.conversation_id = ? AND c.delete_scheduled_at > current_date AND m.withdrawn_at IS NULL "
                + "FOR KEY SHARE OF c", id).isEmpty();
    }

    public long insertQuestion(UUID id, String masked) {
        return jdbc.queryForObject("INSERT INTO ai_message(conversation_id, role, status, content) "
                + "VALUES (?, 'Member', '질문', ?) RETURNING message_id", Long.class, id, masked);
    }

    public Optional<AgentDtos.ActiveQuestion> activeQuestion(UUID id) {
        return jdbc.query("""
                SELECT q.message_id, q.created_at,
                    (SELECT max(m.created_at) FROM ai_message m
                     WHERE m.message_id = q.message_id OR m.question_id = q.message_id) AS last_activity
                FROM ai_message q WHERE q.conversation_id = ? AND q.status = '질문'
                AND NOT EXISTS (SELECT 1 FROM ai_message e WHERE e.question_id = q.message_id
                                AND e.status IN ('완료', '실패', '취소'))
                ORDER BY q.message_id DESC LIMIT 1
                """, (rs, row) -> new AgentDtos.ActiveQuestion(rs.getLong(1), instant(rs, 2), instant(rs, 3)), id)
                .stream().findFirst();
    }

    public boolean questionExists(UUID conversationId, long questionId) {
        return Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM ai_message "
                + "WHERE conversation_id = ? AND message_id = ? AND status = '질문')", Boolean.class, conversationId, questionId));
    }

    public boolean ended(long questionId) {
        return Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM ai_message "
                + "WHERE question_id = ? AND status IN ('완료', '실패', '취소'))", Boolean.class, questionId));
    }

    public void insertAi(UUID id, long questionId, String status, String content, String details) {
        jdbc.update("INSERT INTO ai_message(conversation_id, question_id, role, status, content, details) "
                + "VALUES (?, ?, 'AI', ?, ?, ?)", id, questionId, status, content, details);
    }

    public List<AgentDtos.Message> messages(UUID id, long after) {
        return jdbc.query("SELECT message_id, question_id, role, status, content, details, artifacts::text, created_at "
                + "FROM ai_message WHERE conversation_id = ? AND message_id > ? ORDER BY message_id", (rs, row) -> {
                    String artifacts = rs.getString(7);
                    return new AgentDtos.Message(rs.getLong(1), rs.getObject(2, Long.class), rs.getString(3), rs.getString(4),
                            rs.getString(5), rs.getString(6), artifacts == null ? null : json.readTree(artifacts), instant(rs, 8));
                }, id, after);
    }

    private Instant instant(ResultSet rs, int column) throws SQLException {
        return rs.getObject(column, OffsetDateTime.class).toInstant();
    }
}
