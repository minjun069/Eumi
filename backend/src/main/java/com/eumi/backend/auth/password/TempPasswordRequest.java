package com.eumi.backend.auth.password;

import java.util.Locale;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import org.hibernate.validator.constraints.CodePointLength;
import tools.jackson.core.JsonParser;
import tools.jackson.core.JsonToken;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.ValueDeserializer;
import tools.jackson.databind.annotation.JsonDeserialize;

public record TempPasswordRequest(
        @JsonProperty(required = true) @NotBlank @Email @CodePointLength(max = 254)
        @JsonDeserialize(using = StringValue.class) String email,
        @JsonProperty(required = true) @NotBlank @CodePointLength(max = 100)
        @JsonDeserialize(using = StringValue.class) String name) {
    public TempPasswordRequest {
        if (email != null) email = email.strip().toLowerCase(Locale.ROOT);
        if (name != null) name = name.strip();
    }
    @JsonAnySetter public void unknown(String key, Object value) { throw new IllegalArgumentException("Unknown temporary-password field"); }
    @Override public String toString() { return "TempPasswordRequest[redacted]"; }

    public static class StringValue extends ValueDeserializer<String> {
        @Override public String deserialize(JsonParser parser, DeserializationContext context) {
            if (parser.currentToken() != JsonToken.VALUE_STRING) return context.reportInputMismatch(String.class, "JSON string required");
            return parser.getString();
        }
    }
}
