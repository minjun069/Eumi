package com.eumi.backend.cases;

import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Locale;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.eumi.backend.common.error.ApiErrorResponse;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import jakarta.validation.constraints.*;
import org.hibernate.validator.constraints.CodePointLength;
import org.springframework.format.annotation.DateTimeFormat;

public final class CaseDtos {
    public static final long MAX_ID = 9007199254740991L;
    private static final DateTimeFormatter UPDATED_AT = DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSSSSSxxx",Locale.ROOT)
            .withZone(ZoneId.of("Asia/Seoul"));
    private CaseDtos() { }
    private static String trim(String s) { return s == null ? null : s.trim(); }
    private static String optional(String s) { s = trim(s); return s == null || s.isEmpty() ? null : s; }
    private static String defaulted(String s, String value) { s = optional(s); return s == null ? value : s; }

    public record Input(
            @JsonProperty(required = true) @NotBlank @CodePointLength(max = 100) String name,
            @JsonProperty(required = true) @NotNull LocalDate birthDate,
            @JsonProperty(required = true) @NotNull @Pattern(regexp = "남|여") String gender,
            @JsonProperty(required = true) @NotNull @Pattern(regexp = "[0-9]{10}") String dongCode,
            @JsonProperty(required = true) @NotNull LocalDate firstRegisteredAt,
            @JsonProperty(required = true) @NotNull @Size(min = 1)
            List<@NotNull @Min(1) @Max(MAX_ID) Long> managerMemberIds) {
        public Input { name = trim(name); gender = trim(gender); dongCode = trim(dongCode); }
        @Override public String toString() { return "CaseInput[redacted]"; }
        @JsonAnySetter public void unknown(String key, Object value) { throw new IllegalArgumentException("Unknown case field"); }
    }

    public record UpdateInput(
            @JsonProperty(required = true) @NotBlank @CodePointLength(max = 100) String name,
            @JsonProperty(required = true) @NotNull LocalDate birthDate,
            @JsonProperty(required = true) @NotNull @Pattern(regexp = "남|여") String gender,
            @JsonProperty(required = true) @NotNull @Pattern(regexp = "[0-9]{10}") String dongCode,
            @JsonProperty(required = true) @NotNull LocalDate firstRegisteredAt,
            @JsonProperty(required = true) @NotNull @Size(min = 1)
            List<@NotNull @Min(1) @Max(MAX_ID) Long> managerMemberIds,
            String updatedAt) {
        public UpdateInput { name = trim(name); gender = trim(gender); dongCode = trim(dongCode); }
        public Input input() { return new Input(name,birthDate,gender,dongCode,firstRegisteredAt,managerMemberIds); }
        public Instant expectedUpdatedAt() {
            if(updatedAt != null) {
                try { return OffsetDateTime.parse(updatedAt).toInstant(); }
                catch(DateTimeException ignored) { }
            }
            throw new ApiException(ErrorCode.VALIDATION_ERROR,
                    List.of(new ApiErrorResponse.FieldError("updatedAt","입력값을 확인해 주세요.")));
        }
        @Override public String toString() { return "CaseUpdateInput[redacted]"; }
        @JsonAnySetter public void unknown(String key, Object value) { throw new IllegalArgumentException("Unknown case update field"); }
    }

    static String formatUpdatedAt(Instant value) { return UPDATED_AT.format(value); }

    public record DuplicateInput(
            @JsonProperty(required = true) @NotBlank @CodePointLength(max = 100) String name,
            @JsonProperty(required = true) @NotNull LocalDate birthDate,
            @Min(1) @Max(MAX_ID) Long excludeCaseId) {
        public DuplicateInput { name = trim(name); }
        @Override public String toString() { return "DuplicateInput[redacted]"; }
        @JsonAnySetter public void unknown(String key, Object value) { throw new IllegalArgumentException("Unknown duplicate field"); }
    }

    public record Search(
            @Pattern(regexp = "[0-9]{2}") String sidoCode,
            @Pattern(regexp = "[0-9]{5}") String sigunguCode,
            @Pattern(regexp = "[0-9]{10}") String dongCode,
            @Pattern(regexp = "전체|청소년|청년|중장년|노년") String ageGroup,
            @Pattern(regexp = "전체|남|여") String gender,
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate registeredFrom,
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate registeredTo,
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate recordedFrom,
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate recordedTo,
            String keyword,
            @Pattern(regexp = "name|region|age|gender|firstRegisteredAt|lastRecordedAt") String sort,
            @Pattern(regexp = "asc|desc") String direction,
            @Min(1) @Max(MAX_ID) Long page, @Min(1) @Max(100) Integer size) {
        public Search {
            sidoCode = optional(sidoCode); sigunguCode = optional(sigunguCode); dongCode = optional(dongCode);
            ageGroup = defaulted(ageGroup, "전체"); gender = defaulted(gender, "전체"); keyword = defaulted(keyword, "");
            sort = defaulted(sort, "firstRegisteredAt"); direction = defaulted(direction, "desc");
            page = page == null ? 1L : page; size = size == null ? 10 : size;
        }
        @Override public String toString() { return "CaseSearch[redacted]"; }
    }

    public record ListItem(long caseId, String managementNo, String name, int age, String ageGroup, String gender,
            String sidoName, String sigunguName, String dongName, LocalDate firstRegisteredAt, LocalDate lastRecordedAt) { }
    public record Manager(long memberId, String name, String title) { }
    public record Detail(long caseId, String managementNo, String name, int age, String ageGroup, String gender,
            String sidoName, String sigunguName, String dongName, LocalDate firstRegisteredAt, LocalDate lastRecordedAt,
            LocalDate birthDate, String sidoCode, String sigunguCode, String dongCode, List<Manager> managers, String updatedAt) { }
    public record Page(long totalCount, long page, int size, long totalPages, List<ListItem> items) { }
    public record Duplicate(long caseId, String managementNo, String name) { }
    public record Duplicates(List<Duplicate> duplicates) { }
    public record Created(long caseId, String managementNo) { }
}
