package com.eumi.backend;

import com.eumi.backend.config.PasswordConfiguration;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.security.crypto.password.DelegatingPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

import static org.assertj.core.api.Assertions.assertThat;

class PasswordEncoderTests {
    @ParameterizedTest
    @ValueSource(ints = {8, 72, 73, 128})
    void asciiPasswordsRoundTripWithoutTruncation(int length) {
        verify("Aa1!" + "x".repeat(length - 4));
    }

    @ParameterizedTest
    @ValueSource(strings = {"한", "\uD83D\uDE00"})
    void unicode128CodePointPasswordsRoundTripWithoutTruncation(String character) {
        verify(character.repeat(128));
    }

    private void verify(String raw) {
        new ApplicationContextRunner().withUserConfiguration(PasswordConfiguration.class).run(context -> {
            var encoder = context.getBean(PasswordEncoder.class);
            assertThat(encoder).isInstanceOf(DelegatingPasswordEncoder.class);
            String encoded = encoder.encode(raw);
            assertThat(encoded.startsWith("{pbkdf2}")).isTrue();
            assertThat(encoder.matches(raw, encoded)).isTrue();
            assertThat(encoder.matches(raw.substring(0, raw.length() - 1) + "z", encoded)).isFalse();
            assertThat(encoder.encode(raw).equals(encoded)).isFalse();
        });
    }
}
