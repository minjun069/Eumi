package com.eumi.backend.auth.signup;

import java.util.Locale;
import com.eumi.backend.auth.password.TempPasswordRequest.StringValue;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.*;
import org.hibernate.validator.constraints.CodePointLength;
import tools.jackson.core.JsonParser;
import tools.jackson.core.JsonToken;
import tools.jackson.databind.DeserializationContext;
import tools.jackson.databind.ValueDeserializer;
import tools.jackson.databind.annotation.JsonDeserialize;

public final class SignupDtos {
    private SignupDtos() { }
    private static final long MAX_ID=9007199254740991L;
    private static String email(String value) {return value==null ? null : value.trim().toLowerCase(Locale.ROOT);}
    private static String trim(String value) {return value==null ? null : value.trim();}
    private static String optional(String value) {value=trim(value);return value==null || value.isEmpty() ? null : value;}

    public record SendVerificationRequest(
            @JsonProperty(required=true) @NotNull @Min(1) @Max(MAX_ID) @JsonDeserialize(using=IntegerValue.class) Long orgId,
            @JsonProperty(required=true) @NotBlank @Email @CodePointLength(max=254) @JsonDeserialize(using=StringValue.class) String email) {
        public SendVerificationRequest {email=SignupDtos.email(email);}
        @JsonAnySetter public void unknown(String key,Object value) {throw new IllegalArgumentException("Unknown verification-send field");}
        @Override public String toString() {return "SendVerificationRequest[redacted]";}
    }
    public record VerifyCodeRequest(
            @JsonProperty(required=true) @NotBlank @Email @CodePointLength(max=254) @JsonDeserialize(using=StringValue.class) String email,
            @JsonProperty(required=true) @NotNull @Pattern(regexp="[0-9]{6}") @JsonDeserialize(using=StringValue.class) String code) {
        public VerifyCodeRequest {email=SignupDtos.email(email);}
        @JsonAnySetter public void unknown(String key,Object value) {throw new IllegalArgumentException("Unknown verification-code field");}
        @Override public String toString() {return "VerifyCodeRequest[redacted]";}
    }
    public record SignupRequest(
            @JsonProperty(required=true) @NotBlank @CodePointLength(max=256) @JsonDeserialize(using=StringValue.class) String verificationToken,
            @JsonProperty(required=true) @NotNull @Min(1) @Max(MAX_ID) @JsonDeserialize(using=IntegerValue.class) Long orgId,
            @JsonProperty(required=true) @NotBlank @Email @CodePointLength(max=254) @JsonDeserialize(using=StringValue.class) String email,
            @JsonProperty(required=true) @NotBlank @CodePointLength(max=100) @JsonDeserialize(using=StringValue.class) String name,
            @JsonProperty(required=true) @NotNull @CodePointLength(min=8,max=128)
            @Pattern(regexp="^(?=.*[A-Za-z])(?=.*[0-9])(?=.*[^A-Za-z0-9]).{8,}$") @JsonDeserialize(using=StringValue.class) String password,
            @CodePointLength(max=100) @JsonDeserialize(using=StringValue.class) String title,
            @Pattern(regexp="^01[016789]-[0-9]{3,4}-[0-9]{4}$") @JsonDeserialize(using=StringValue.class) String phone) {
        public SignupRequest {email=SignupDtos.email(email);name=trim(name);title=optional(title);}
        @JsonAnySetter public void unknown(String key,Object value) {throw new IllegalArgumentException("Unknown signup field");}
        @Override public String toString() {return "SignupRequest[redacted]";}
    }
    public record OrganizationSearchItem(long orgId,String orgName,String sidoName,String sigunguName,String officialDomain) { }
    public record VerificationSent(String expiresAt) { }
    public record VerificationTokenData(String verificationToken) {
        @Override public String toString() {return "VerificationTokenData[redacted]";}
    }
    public record MemberCreated(long memberId) { }

    public static class IntegerValue extends ValueDeserializer<Long> {
        @Override public Long deserialize(JsonParser parser,DeserializationContext context) {
            if(parser.currentToken()!=JsonToken.VALUE_NUMBER_INT) return context.reportInputMismatch(Long.class,"JSON integer required");
            return parser.getLongValue();
        }
    }
}
