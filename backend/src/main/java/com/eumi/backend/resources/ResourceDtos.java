package com.eumi.backend.resources;

import java.time.LocalDate;
import java.util.*;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.*;
import org.hibernate.validator.constraints.CodePointLength;

public final class ResourceDtos {
    public static final long MAX_ID = 9007199254740991L;
    public static final long MAX_INTEGER = 2147483647L;
    private ResourceDtos() { }
    private static String trim(String s) { return s == null ? null : s.trim(); }
    private static String optional(String s) { s=trim(s); return s==null || s.isEmpty() ? null : s; }
    private static String defaulted(String s, String fallback) { s=optional(s); return s==null ? fallback : s; }

    public record Input(
            @JsonProperty(required=true) @NotBlank @CodePointLength(max=50) String resourceName,
            @JsonProperty(required=true) @NotBlank @CodePointLength(max=50) String operatingOrgName,
            @JsonProperty(required=true) @NotBlank @CodePointLength(max=100) String target,
            @JsonProperty(required=true) @NotNull @Size(min=1) List<String> supportAgeGroups,
            @JsonProperty(required=true) @NotNull @Pattern(regexp="남|여|무관") String supportGender,
            @JsonProperty(required=true) @NotNull @Pattern(regexp="[0-9]{5}") String sigunguCode,
            @Pattern(regexp="[0-9]{10}") String dongCode,
            @JsonProperty(required=true) @NotNull LocalDate periodStart,
            @JsonProperty(required=true) @NotNull LocalDate periodEnd,
            @JsonProperty(required=true) @NotNull @Min(0) @Max(MAX_INTEGER) Long fee,
            @JsonProperty(required=true) @NotNull @Pattern(regexp="진행 중|종료") String status,
            @JsonProperty(required=true) @NotNull @Min(1) @Max(MAX_ID) Long managerMemberId,
            @JsonProperty(required=true) @NotNull @Min(1) @Max(MAX_INTEGER) Long capacity,
            @Min(0) @Max(MAX_INTEGER) Long actualParticipants,
            @CodePointLength(max=1000) String supportContent,
            @CodePointLength(max=200) String applyMethod) {
        public Input {
            resourceName=trim(resourceName); operatingOrgName=trim(operatingOrgName); target=trim(target);
            supportGender=trim(supportGender); sigunguCode=trim(sigunguCode); dongCode=trim(dongCode); status=trim(status);
            supportContent=optional(supportContent); applyMethod=optional(applyMethod);
            if(supportAgeGroups!=null) supportAgeGroups=Collections.unmodifiableList(
                    new ArrayList<>(new LinkedHashSet<>(supportAgeGroups.stream().map(ResourceDtos::trim).toList())));
        }
        @Override public String toString() { return "ResourceInput[redacted]"; }
        @JsonAnySetter public void unknown(String key,Object value) { throw new IllegalArgumentException("Unknown resource field"); }
    }

    public record Search(
            @Pattern(regexp="[0-9]{2}") String sidoCode,
            @Pattern(regexp="[0-9]{5}") String sigunguCode,
            @Pattern(regexp="[0-9]{10}") String dongCode,
            @Pattern(regexp="전체|청소년|청년|중장년|노년") String ageGroup,
            @Pattern(regexp="전체|남|여") String gender,
            @Min(0) @Max(MAX_INTEGER) Long capacityMin, @Min(0) @Max(MAX_INTEGER) Long capacityMax,
            @CodePointLength(max=50) String resourceName, String managerName,
            @Pattern(regexp="resourceName|capacity|periodEnd|fee") String sort,
            @Pattern(regexp="asc|desc") String direction,
            @Min(1) @Max(MAX_ID) Long page, @Min(1) @Max(100) Integer size) {
        public Search {
            sidoCode=optional(sidoCode); sigunguCode=optional(sigunguCode); dongCode=optional(dongCode);
            ageGroup=defaulted(ageGroup,"전체"); gender=defaulted(gender,"전체");
            resourceName=defaulted(resourceName,""); managerName=defaulted(managerName,"");
            sort=defaulted(sort,"periodEnd"); direction=defaulted(direction,"asc");
            page=page==null ? 1L : page; size=size==null ? 10 : size;
        }
        @Override public String toString() { return "ResourceSearch[redacted]"; }
    }

    public record ListItem(long resourceId,String resourceName,String operatingOrgName,String target,int capacity,
            String sigunguName,String dongName,LocalDate periodStart,LocalDate periodEnd,int fee,String status) { }
    public record Manager(long memberId,String name,String title,String orgName,boolean withdrawn) { }
    public record Detail(long resourceId,String resourceName,String operatingOrgName,String target,int capacity,
            String sigunguName,String dongName,LocalDate periodStart,LocalDate periodEnd,int fee,String status,
            List<String> supportAgeGroups,String supportGender,String sidoCode,String sidoName,String sigunguCode,
            String dongCode,boolean autoEnded,Integer actualParticipants,String supportContent,String applyMethod,
            Manager manager,boolean editable,String manualStatus) { }
    public record Page(long totalCount,long page,int size,long totalPages,List<ListItem> items) { }
    public record Created(long resourceId) { }
}
