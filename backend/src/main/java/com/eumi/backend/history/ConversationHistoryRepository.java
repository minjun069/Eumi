package com.eumi.backend.history;

import java.sql.*;
import java.time.*;
import java.util.*;
import com.eumi.backend.common.error.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ConversationHistoryRepository {
    private static final Logger log=LoggerFactory.getLogger(ConversationHistoryRepository.class);
    private final JdbcTemplate jdbc;
    public ConversationHistoryRepository(JdbcTemplate jdbc) {this.jdbc=jdbc;}
    public ConversationHistoryDtos.Page list(long member,ConversationHistoryDtos.Search s) {
        long count=jdbc.queryForObject("SELECT count(*) FROM public.v_conversation_summary WHERE member_id=?",Long.class,member);
        long pages=count==0 ? 0 : (count-1)/s.size()+1,page=pages==0 ? 1 : Math.min(s.page(),pages);
        var items=jdbc.query("""
                SELECT * FROM public.v_conversation_summary WHERE member_id=?
                ORDER BY last_message_at DESC,conversation_id ASC LIMIT ? OFFSET ?
                """,this::item,member,s.size(),(page-1)*s.size());
        return new ConversationHistoryDtos.Page(count,page,s.size(),pages,items);
    }
    public ConversationHistoryDtos.Item info(long member,UUID id) {
        return jdbc.query("SELECT * FROM public.v_conversation_summary WHERE member_id=? AND conversation_id=?",
                this::item,member,id).stream().findFirst().orElseThrow(()->new ApiException(ErrorCode.NOT_FOUND));
    }
    private ConversationHistoryDtos.Item item(ResultSet rs,int row)throws SQLException {
        var id=rs.getObject("conversation_id",UUID.class);String question=rs.getString("first_question");
        long count=rs.getLong("question_count");
        if(question==null || count<1) {
            log.warn("Invalid saved conversation summary conversationId={}",id);throw new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
        }
        return new ConversationHistoryDtos.Item(id,question,count,rs.getObject("last_message_at",OffsetDateTime.class).toInstant(),
                rs.getObject("delete_scheduled_at",LocalDate.class));
    }
    public void delete(long member,UUID id) {
        if(jdbc.update("DELETE FROM public.ai_conversation WHERE conversation_id=? AND member_id=?",id,member)!=1) {
            throw new ApiException(ErrorCode.NOT_FOUND);
        }
    }
}
