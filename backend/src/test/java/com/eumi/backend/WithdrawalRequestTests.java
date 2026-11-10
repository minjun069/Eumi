package com.eumi.backend;

import java.util.*;
import com.eumi.backend.common.error.*;
import com.eumi.backend.mypage.WithdrawalDtos;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;

class WithdrawalRequestTests {
    private final JsonMapper json=JsonMapper.builder().build();
    private Map<String,Object> input() {
        return new HashMap<>(Map.of("password",UUID.randomUUID().toString(),"transfers",List.of(),"resourceTransfers",List.of()));
    }
    private WithdrawalDtos.Request parse(Object value) { return WithdrawalDtos.Request.parse(json.valueToTree(value)); }
    private void invalid(Object value,ErrorCode code) {
        assertThatThrownBy(()->parse(value)).isInstanceOfSatisfying(ApiException.class,e->assertThat(e.code()).isEqualTo(code));
    }
    @Test void passwordIsNotTrimmedAndItsLengthUsesCodePoints() {
        var body=input();String raw=" "+UUID.randomUUID()+" ";body.put("password",raw);
        var request=parse(body);assertThat(request.password().equals(raw)).isTrue();request.validateFor(1);
        assertThat(request.toString()).isEqualTo("WithdrawalRequest[redacted]");
        body.put("password","😀".repeat(128));assertThat(parse(body).password().codePointCount(0,256)).isEqualTo(128);
        body.put("password","😀".repeat(129));invalid(body,ErrorCode.VALIDATION_ERROR);
        body.put("password","");invalid(body,ErrorCode.VALIDATION_ERROR);
        body.put("password"," ");parse(body);
    }
    @ParameterizedTest @ValueSource(strings={"password","transfers","resourceTransfers"})
    void requiredFieldsRejectMissingNullAndWrongTypes(String field) {
        var body=input();body.remove(field);invalid(body,ErrorCode.INVALID_JSON);
        body.put(field,null);invalid(body,ErrorCode.VALIDATION_ERROR);
        body.put(field,123);invalid(body,ErrorCode.INVALID_JSON);
    }
    @Test void unknownFieldsWrongRootAndNestedShapesAreInvalidJson() {
        var body=input();body.put("extra",true);invalid(body,ErrorCode.INVALID_JSON);
        invalid(List.of(),ErrorCode.INVALID_JSON);
        body=input();body.put("transfers",List.of(Map.of("caseId",1)));invalid(body,ErrorCode.INVALID_JSON);
        body.put("transfers",List.of(Map.of("caseId",1,"newManagerMemberId",2,"extra",true)));invalid(body,ErrorCode.INVALID_JSON);
        body.put("transfers",List.of(Map.of("caseId","1","newManagerMemberId",2)));invalid(body,ErrorCode.INVALID_JSON);
        body.put("transfers",List.of(Map.of("caseId",1.5,"newManagerMemberId",2)));invalid(body,ErrorCode.INVALID_JSON);
        body.put("transfers",List.of(1));invalid(body,ErrorCode.INVALID_JSON);
        body=input();body.put("resourceTransfers",List.of(Map.of("resourceId",1,"newManagerMemberId",2,"extra",true)));invalid(body,ErrorCode.INVALID_JSON);
    }
    @ParameterizedTest @ValueSource(longs={0,-1,9007199254740992L})
    void idsFollowContractBounds(long bad) {
        var body=input();body.put("transfers",List.of(Map.of("caseId",bad,"newManagerMemberId",2)));invalid(body,ErrorCode.VALIDATION_ERROR);
        body=input();body.put("resourceTransfers",List.of(Map.of("resourceId",1,"newManagerMemberId",bad)));invalid(body,ErrorCode.VALIDATION_ERROR);
    }
    @Test void duplicateTargetsAndSelfSuccessorsHaveArrayFieldErrors() {
        var cases=new WithdrawalDtos.Transfer(10,2);var resource=new WithdrawalDtos.ResourceTransfer(20,2);
        var requests=List.of(new WithdrawalDtos.Request(UUID.randomUUID().toString(),List.of(cases,cases),List.of()),
                new WithdrawalDtos.Request(UUID.randomUUID().toString(),List.of(),List.of(resource,resource)),
                new WithdrawalDtos.Request(UUID.randomUUID().toString(),List.of(new WithdrawalDtos.Transfer(10,1)),List.of()),
                new WithdrawalDtos.Request(UUID.randomUUID().toString(),List.of(),List.of(new WithdrawalDtos.ResourceTransfer(20,1))));
        for (int i=0;i<requests.size();i++) {
            var request=requests.get(i);String field=i%2==0 ? "transfers" : "resourceTransfers";
            assertThatThrownBy(()->request.validateFor(1)).isInstanceOfSatisfying(ApiException.class,e->{
                assertThat(e.code()).isEqualTo(ErrorCode.VALIDATION_ERROR);assertThat(e.fieldErrors().getFirst().field()).isEqualTo(field);
            });
        }
    }
}
