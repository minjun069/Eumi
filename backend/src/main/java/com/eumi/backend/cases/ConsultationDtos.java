package com.eumi.backend.cases;

import java.time.LocalDate;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.*;
import org.hibernate.validator.constraints.CodePointLength;

public final class ConsultationDtos {
    private ConsultationDtos() { }
    private static String trim(String s) { return s == null ? null : s.trim(); }

    public record Input(
            @JsonProperty(required = true) @NotNull LocalDate consultedAt,
            @JsonProperty(required = true) @NotBlank @CodePointLength(max = 200) String purpose,
            @JsonProperty(required = true) @NotNull @Pattern(regexp = "초기상담|중기상담|종료상담|정기상담|긴급상담|기타") String category,
            @CodePointLength(max = 20) String categoryEtc,
            @JsonProperty(required = true) @NotBlank @CodePointLength(max = 20000) String content) {
        public Input {
            purpose = trim(purpose); category = trim(category); content = trim(content);
            categoryEtc = "기타".equals(category) ? trim(categoryEtc) : null;
        }
        @Override public String toString() { return "ConsultationInput[redacted]"; }
        @JsonAnySetter public void unknown(String key, Object value) { throw new IllegalArgumentException("Unknown consultation field"); }
    }
    public record ListItem(long consultationId, LocalDate consultedAt, String purpose, String category,
            String categoryEtc, String recorderName) { }
    public record Detail(long consultationId, LocalDate consultedAt, String purpose, String category,
            String categoryEtc, String recorderName, String content, long recorderMemberId) { }
    public record Created(long consultationId) { }
}
