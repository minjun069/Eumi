package com.eumi.backend.auth.password;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.*;
import org.hibernate.validator.constraints.CodePointLength;

public record PasswordChangeRequest(
        @JsonProperty(required=true) @NotNull @CodePointLength(min=1,max=128) String currentPassword,
        @JsonProperty(required=true) @NotNull @CodePointLength(min=8,max=128)
        @Pattern(regexp="^(?=.*[A-Za-z])(?=.*[0-9])(?=.*[^A-Za-z0-9]).{8,}$") String newPassword) {
    // 비밀번호는 trim하거나 정규화하지 않는다.
    @Override public String toString() {return "PasswordChangeRequest[redacted]";}
    @JsonAnySetter public void unknown(String key,Object value) {throw new IllegalArgumentException("Unknown password-change field");}
}
