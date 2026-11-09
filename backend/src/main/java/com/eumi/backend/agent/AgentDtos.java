package com.eumi.backend.agent;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonInclude;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import org.hibernate.validator.constraints.CodePointLength;
import tools.jackson.databind.JsonNode;
import tools.jackson.core.JsonParser;
import tools.jackson.core.JsonToken;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.ValueDeserializer;
import tools.jackson.databind.annotation.JsonDeserialize;

public final class AgentDtos {
    private AgentDtos() { }

    public record QuestionRequest(@JsonProperty(required = true) UUID conversationId,
            @JsonProperty(required = true) @NotBlank @CodePointLength(min = 1, max = 4000) String question,
            @Valid ScreenContext context) {
        public QuestionRequest(UUID conversationId, String question) { this(conversationId, question, null); }
        public QuestionRequest {
            if (question != null) question = question.trim();
        }
        @Override public String toString() { return "QuestionRequest[redacted]"; }
        @JsonAnySetter
        public void rejectUnknown(String key, Object value) { throw new IllegalArgumentException("Unknown question field"); }
    }

    public record QuestionCreated(UUID conversationId, long questionId) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ScreenContext(
            @Pattern(regexp = "[0-9]{10}") @JsonDeserialize(using = StringValue.class) String dongCode,
            @Pattern(regexp = "(?!0000)[0-9]{4}-(0[1-9]|1[0-2])") @JsonDeserialize(using = StringValue.class) String month) {
        @JsonAnySetter
        public void rejectUnknown(String key, Object value) { throw new IllegalArgumentException("Unknown context field"); }
    }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record RunRequest(UUID conversationId, long messageId, ScreenContext context) { }
    public record Notification(@NotNull UUID conversationId,
            @NotNull @Positive @JsonDeserialize(using = IntegerValue.class) Long messageId) {
        @JsonAnySetter
        public void rejectUnknown(String key, Object value) { throw new IllegalArgumentException("Unknown notification field"); }
    }
    public record StoredNotification(long questionId, String status) { }

    public static class StringValue extends ValueDeserializer<String> {
        @Override public String deserialize(JsonParser parser, DeserializationContext context) {
            if (parser.currentToken() != JsonToken.VALUE_STRING) return context.reportInputMismatch(String.class, "JSON string required");
            return parser.getString();
        }
    }
    public static class IntegerValue extends ValueDeserializer<Long> {
        @Override public Long deserialize(JsonParser parser, DeserializationContext context) {
            if (parser.currentToken() != JsonToken.VALUE_NUMBER_INT) return context.reportInputMismatch(Long.class, "JSON integer required");
            return parser.getLongValue();
        }
    }
    public record Message(long messageId, Long questionId, String role, String status,
            String content, String details, JsonNode artifacts, Instant createdAt) {
        @Override public String toString() { return "Message[redacted]"; }
    }
    public record Messages(List<Message> messages) { }
    public record ActiveQuestion(long questionId, Instant askedAt, Instant lastActivityAt) { }
}
