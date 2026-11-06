package com.eumi.backend.history;

import java.time.*;
import java.util.*;
import com.eumi.backend.agent.AgentDtos;
import jakarta.validation.constraints.*;

public final class ConversationHistoryDtos {
    private ConversationHistoryDtos() { }
    public record Search(@Min(1) @Max(9007199254740991L) Long page,@Min(1) @Max(100) Integer size) {
        public Search {page=page==null ? 1L : page;size=size==null ? 10 : size;}
    }
    public record Item(UUID conversationId,String firstQuestion,long questionCount,Instant lastMessageAt,LocalDate deleteScheduledAt) {
        @Override public String toString() {return "ConversationHistoryItem[redacted]";}
    }
    public record Page(long totalCount,long page,int size,long totalPages,List<Item> items) { }
    public record Detail(UUID conversationId,String firstQuestion,Instant lastMessageAt,LocalDate deleteScheduledAt,
            List<AgentDtos.Message> messages) {
        @Override public String toString() {return "ConversationHistoryDetail[redacted]";}
    }
}
