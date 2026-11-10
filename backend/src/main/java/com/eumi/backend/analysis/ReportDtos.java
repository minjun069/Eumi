package com.eumi.backend.analysis;

import java.util.List;
import java.util.UUID;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.PositiveOrZero;
import org.hibernate.validator.constraints.CodePointLength;
import tools.jackson.core.JsonParser;
import tools.jackson.core.JsonToken;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.ValueDeserializer;
import tools.jackson.databind.annotation.JsonDeserialize;

public final class ReportDtos {
    private ReportDtos() { }

    public record PipelineCompletion(
            @NotNull @Pattern(regexp = "(?!0000)[0-9]{4}-(0[1-9]|1[0-2])") @JsonDeserialize(using = StringValue.class) String month,
            @CodePointLength(min = 1, max = 200) @JsonDeserialize(using = StringValue.class) String pipelineRunId,
            @Pattern(regexp = "FULL|RESULT_RELOAD|ANALYSIS_RELOAD") @JsonDeserialize(using = StringValue.class) String reason) {
        public PipelineCompletion {
            if (pipelineRunId != null) pipelineRunId = pipelineRunId.strip();
            if (reason == null) reason = "FULL";
        }
        @JsonAnySetter public void rejectUnknown(String key, Object value) { throw new IllegalArgumentException("Unknown report field"); }
    }
    public record Accepted(String month, int targetCount) { }
    public record GenerationRequest(UUID requestId, String month, List<String> dongCodes) { }
    public record Completion(@NotNull @JsonDeserialize(using = StringValue.class) String requestId,
            @NotNull @Pattern(regexp = "(?!0000)[0-9]{4}-(0[1-9]|1[0-2])") @JsonDeserialize(using = StringValue.class) String month,
            @NotNull @PositiveOrZero @JsonDeserialize(using = CountValue.class) Long savedCount,
            @NotNull @JsonDeserialize(contentUsing = StringValue.class)
            List<@NotNull @Pattern(regexp = "[0-9]{10}") String> failedDongCodes) {
        @JsonAnySetter public void rejectUnknown(String key, Object value) { throw new IllegalArgumentException("Unknown report field"); }
    }

    // 타입 자동 변환을 허용하지 않는다. 값의 제약은 Bean Validation이 검사한다.
    public static class StringValue extends ValueDeserializer<String> {
        @Override public String deserialize(JsonParser parser, DeserializationContext context) {
            if (parser.currentToken() != JsonToken.VALUE_STRING) return context.reportInputMismatch(String.class, "JSON string required");
            return parser.getString();
        }
    }
    public static class CountValue extends ValueDeserializer<Long> {
        @Override public Long deserialize(JsonParser parser, DeserializationContext context) {
            if (parser.currentToken() != JsonToken.VALUE_NUMBER_INT) return context.reportInputMismatch(Long.class, "JSON integer required");
            return parser.getLongValue();
        }
    }
}
