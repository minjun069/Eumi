package com.eumi.backend.mypage;

import java.time.LocalDate;
import java.util.*;
import com.eumi.backend.common.error.*;
import tools.jackson.databind.JsonNode;

public final class WithdrawalDtos {
    private WithdrawalDtos() { }
    public record SoleCase(long caseId, String managementNo, String name, String ageGroup,
            String dongName, LocalDate lastRecordedAt) { }
    public record Successor(long memberId, String name, String title) { }
    public record OngoingResource(long resourceId, String resourceName, LocalDate periodEnd) { }
    public record Info(List<SoleCase> soleCases, long sharedCaseCount, List<Successor> successors,
            long resourceCount, long conversationCount, List<OngoingResource> ongoingResources,
            long endedResourceCount) { }
    public record Transfer(long caseId, long newManagerMemberId) { }
    public record ResourceTransfer(long resourceId, long newManagerMemberId) { }

    public record Request(String password, List<Transfer> transfers, List<ResourceTransfer> resourceTransfers) {
        public Request { transfers = List.copyOf(transfers); resourceTransfers = List.copyOf(resourceTransfers); }
        @Override public String toString() { return "WithdrawalRequest[redacted]"; }

        public static Request parse(JsonNode body) {
            object(body, Set.of("password", "transfers", "resourceTransfers"));
            var password = required(body, "password");
            if (password.isNull()) throw invalid("password");
            if (!password.isString()) throw new ApiException(ErrorCode.INVALID_JSON);
            String raw = password.asText();
            if (raw.codePointCount(0, raw.length()) < 1 || raw.codePointCount(0, raw.length()) > 128) throw invalid("password");
            var cases = new ArrayList<Transfer>();
            for (var item : array(body, "transfers")) {
                object(item, Set.of("caseId", "newManagerMemberId"));
                cases.add(new Transfer(id(item, "caseId", "transfers"), id(item, "newManagerMemberId", "transfers")));
            }
            var resources = new ArrayList<ResourceTransfer>();
            for (var item : array(body, "resourceTransfers")) {
                object(item, Set.of("resourceId", "newManagerMemberId"));
                resources.add(new ResourceTransfer(id(item, "resourceId", "resourceTransfers"), id(item, "newManagerMemberId", "resourceTransfers")));
            }
            return new Request(raw, cases, resources);
        }
        public void validateFor(long member) {
            var cases = new HashSet<Long>();
            for (var item : transfers) {
                if (!cases.add(item.caseId()) || item.newManagerMemberId() == member) throw invalid("transfers");
            }
            var resources = new HashSet<Long>();
            for (var item : resourceTransfers) {
                if (!resources.add(item.resourceId()) || item.newManagerMemberId() == member) throw invalid("resourceTransfers");
            }
        }
        private static void object(JsonNode value, Set<String> fields) {
            if (value == null || !value.isObject() || value.properties().stream().anyMatch(p -> !fields.contains(p.getKey()))) {
                throw new ApiException(ErrorCode.INVALID_JSON);
            }
        }
        private static JsonNode required(JsonNode body, String field) {
            if (!body.has(field)) throw new ApiException(ErrorCode.INVALID_JSON);
            return body.get(field);
        }
        private static JsonNode array(JsonNode body, String field) {
            var value = required(body, field);
            if (value.isNull()) throw invalid(field);
            if (!value.isArray()) throw new ApiException(ErrorCode.INVALID_JSON);
            return value;
        }
        private static long id(JsonNode item, String key, String field) {
            var value = required(item, key);
            if (value.isNull()) throw invalid(field);
            if (!value.isIntegralNumber()) throw new ApiException(ErrorCode.INVALID_JSON);
            if (!value.canConvertToLong() || value.asLong() < 1 || value.asLong() > 9007199254740991L) throw invalid(field);
            return value.asLong();
        }
        private static ApiException invalid(String field) {
            return new ApiException(ErrorCode.VALIDATION_ERROR,
                    List.of(new ApiErrorResponse.FieldError(field, "입력값을 확인해 주세요.")));
        }
    }
}
