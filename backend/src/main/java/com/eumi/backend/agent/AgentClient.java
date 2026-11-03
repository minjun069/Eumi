package com.eumi.backend.agent;

import java.util.UUID;

public interface AgentClient {
    void start(UUID conversationId, long questionId);
    void cancel(UUID conversationId);
    RunStatus status(UUID conversationId);

    record RunStatus(boolean running, Long questionId) { }

    final class Unavailable extends RuntimeException {
        public Unavailable() { super("AI client request failed"); }
    }
}
