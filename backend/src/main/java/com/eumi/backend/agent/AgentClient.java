package com.eumi.backend.agent;

import java.util.UUID;

public interface AgentClient {
    void start(UUID conversationId, long questionId, AgentDtos.ScreenContext context);
    default void start(UUID conversationId, long questionId) { start(conversationId, questionId, null); }
    void cancel(UUID conversationId);

    final class Unavailable extends RuntimeException {
        public Unavailable() { super("AI client request failed"); }
    }
}
