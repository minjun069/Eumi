package com.eumi.backend.config;

import java.util.Map;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.password.DelegatingPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.crypto.password.Pbkdf2PasswordEncoder;

@Configuration(proxyBeanMethods = false)
public class PasswordConfiguration {
    @Bean
    PasswordEncoder passwordEncoder() {
        return new DelegatingPasswordEncoder("pbkdf2",
                Map.of("pbkdf2", Pbkdf2PasswordEncoder.defaultsForSpringSecurity_v5_8()));
    }
}
