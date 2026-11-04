package com.eumi.backend;

import java.util.*;
import com.eumi.backend.auth.password.PasswordChangeRequest;
import jakarta.validation.Validation;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.assertj.core.api.Assertions.*;

class PasswordChangeRequestTests {
    @ParameterizedTest @ValueSource(strings={"short","abcdefgh1","abcdefgh!","12345678!","Ab1!\nxxxx"})
    void newPasswordMustSatisfyContract(String value) {
        try(var factory=Validation.buildDefaultValidatorFactory()) {
            var fields=factory.getValidator().validate(new PasswordChangeRequest(UUID.randomUUID().toString(),value)).stream().map(v->v.getPropertyPath().toString()).toList();
            assertThat(fields).contains("newPassword");
        }
    }
    @ParameterizedTest @ValueSource(ints={128,129})
    void unicodeLengthUsesCodePoints(int length) {
        String value="Aa1!"+"😀".repeat(length-4);
        try(var factory=Validation.buildDefaultValidatorFactory()) {
            var fields=factory.getValidator().validate(new PasswordChangeRequest("😀".repeat(length),value)).stream().map(v->v.getPropertyPath().toString()).toList();
            assertThat(fields.isEmpty()).isEqualTo(length==128);
            if(length==129)assertThat(fields).contains("currentPassword","newPassword");
        }
    }
    @Test
    void requestRetainsWhitespaceAndDoesNotExposeCredentialsInToString() {
        String current=" "+UUID.randomUUID()+" ",next=" "+UUID.randomUUID()+"Aa1! ";var request=new PasswordChangeRequest(current,next);
        assertThat(request.currentPassword().equals(current)).isTrue();assertThat(request.newPassword().equals(next)).isTrue();
        assertThat(request.toString().contains(current) || request.toString().contains(next)).isFalse();
    }
}
