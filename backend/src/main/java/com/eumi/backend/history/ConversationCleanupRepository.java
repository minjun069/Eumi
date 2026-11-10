package com.eumi.backend.history;

import java.time.LocalDate;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ConversationCleanupRepository {
    private final JdbcTemplate jdbc;
    public ConversationCleanupRepository(JdbcTemplate jdbc) { this.jdbc=jdbc; }
    public record Candidate(UUID conversationId,LocalDate deleteScheduledAt) { }

    public List<Candidate> findExpired(LocalDate today,UUID after) {
        String sql="SELECT conversation_id,delete_scheduled_at FROM public.ai_conversation WHERE delete_scheduled_at <= ?"
                +(after==null ? "" : " AND conversation_id > ?")+" ORDER BY conversation_id LIMIT 500";
        Object[] args=after==null ? new Object[]{today} : new Object[]{today,after};
        return jdbc.query(sql,(rs,row)->new Candidate(rs.getObject(1,UUID.class),rs.getObject(2,LocalDate.class)),args);
    }
    public int deleteExpired(UUID id,LocalDate today) {
        return jdbc.update("DELETE FROM public.ai_conversation WHERE conversation_id = ? AND delete_scheduled_at <= ?",id,today);
    }
    public int deleteCancelled(UUID id) {
        return jdbc.update("DELETE FROM public.ai_conversation WHERE conversation_id = ?",id);
    }
    public void restoreExpiry(Candidate candidate) {
        jdbc.update("UPDATE public.ai_conversation SET delete_scheduled_at = ? WHERE conversation_id = ?",
                candidate.deleteScheduledAt(),candidate.conversationId());
    }
}
