package com.eumi.backend;

import java.util.*;
import com.eumi.backend.common.error.*;
import com.eumi.backend.mypage.MyDtos;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;

class MyPatchTests {
    private final JsonMapper json=JsonMapper.builder().build();
    @Test
    void distinguishesOmissionNullAndBlankWithoutExposingPhone() {
        var omitted=MyDtos.Patch.parse(json.readTree("{\"title\":\" Synthetic title \"}"));
        assertThat(omitted.titlePresent()).isTrue();assertThat(omitted.title()).isEqualTo("Synthetic title");
        assertThat(omitted.phonePresent()).isFalse();
        var cleared=MyDtos.Patch.parse(json.readTree("{\"title\":\"  \",\"phone\":null}"));
        assertThat(cleared.title()).isNull();assertThat(cleared.phonePresent()).isTrue();assertThat(cleared.phone()).isNull();
        var phone=MyDtos.Patch.parse(json.readTree("{\"phone\":\"010-0000-0000\"}"));assertThat(phone.toString()).doesNotContain("010-0000-0000");
    }
    @ParameterizedTest @ValueSource(ints={100,101})
    void titleLengthUsesCodePoints(int count) {
        var node=json.valueToTree(Map.of("title","😀".repeat(count)));
        if(count==100)assertThat(MyDtos.Patch.parse(node).title().codePointCount(0,count*2)).isEqualTo(100);
        else assertThatThrownBy(()->MyDtos.Patch.parse(node)).isInstanceOfSatisfying(ApiException.class,
                e->{assertThat(e.code()).isEqualTo(ErrorCode.VALIDATION_ERROR);assertThat(e.fieldErrors()).extracting(ApiErrorResponse.FieldError::field).containsExactly("title");});
    }
    @ParameterizedTest @ValueSource(strings={"{\"phone\":\"\"}","{\"phone\":\"  \"}","{\"phone\":\"01000000000\"}","{\"phone\":\"012-0000-0000\"}","{}"})
    void invalidValuesAreValidationErrors(String body) {
        assertThatThrownBy(()->MyDtos.Patch.parse(json.readTree(body))).isInstanceOfSatisfying(ApiException.class,
                e->assertThat(e.code()).isEqualTo(ErrorCode.VALIDATION_ERROR));
    }
    @ParameterizedTest @ValueSource(strings={"[]","null","{\"name\":\"Synthetic\"}","{\"phone\":123}","{\"title\":false}","{\"title\":{}}"})
    void wrongShapeAndUnknownFieldsAreInvalidJson(String body) {
        assertThatThrownBy(()->MyDtos.Patch.parse(json.readTree(body))).isInstanceOfSatisfying(ApiException.class,
                e->assertThat(e.code()).isEqualTo(ErrorCode.INVALID_JSON));
    }
}
