package com.eumi.backend.auth.login;

import java.util.Locale;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import org.hibernate.validator.constraints.CodePointLength;

public record LoginRequest(
        @NotBlank @Email @Size(max = 254) String email,
        @NotNull @CodePointLength(min = 1, max = 128) String password) {
    public LoginRequest {
        if (email != null) email = email.trim().toLowerCase(Locale.ROOT);
    }

    @Override
    public String toString() { return "LoginRequest[redacted]"; }
}
