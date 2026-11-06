package com.eumi.backend.agent;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonProperty;

import jakarta.validation.constraints.NotBlank;
import org.hibernate.validator.constraints.CodePointLength;
import tools.jackson.databind.JsonNode;

public final class AgentDtos {
    private AgentDtos() { }

    public record QuestionRequest(@JsonProperty(required = true) UUID conversationId,
            @JsonProperty(required = true) @NotBlank @CodePointLength(min = 1, max = 4000) String question) {
        public QuestionRequest {
            if (question != null) question = question.trim();
        }
        @Override public String toString() { return "QuestionRequest[redacted]"; }
        @JsonAnySetter
        public void rejectUnknown(String key, Object value) { throw new IllegalArgumentException("Unknown question field"); }
    }

    public record QuestionCreated(UUID conversationId, long questionId) { }
    public record Message(long messageId, Long questionId, String role, String status,
            String content, String details, JsonNode artifacts, Instant createdAt) {
        @Override public String toString() { return "Message[redacted]"; }
    }
    public record Messages(List<Message> messages) { }
    public record ActiveQuestion(long questionId, Instant askedAt, Instant lastActivityAt) { }
}
