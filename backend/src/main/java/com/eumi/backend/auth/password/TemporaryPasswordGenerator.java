package com.eumi.backend.auth.password;

import java.security.SecureRandom;
import org.springframework.stereotype.Component;

@Component
public class TemporaryPasswordGenerator {
    private static final String UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    private static final String LOWER = "abcdefghijkmnpqrstuvwxyz";
    private static final String DIGITS = "23456789";
    private static final String SPECIAL = "!@#$%^&*";
    private static final String ALL = UPPER + LOWER + DIGITS + SPECIAL;
    private final SecureRandom random = new SecureRandom();

    public String generate() {
        char[] value = new char[12];
        value[0] = pick(UPPER); value[1] = pick(LOWER); value[2] = pick(DIGITS); value[3] = pick(SPECIAL);
        for (int i = 4; i < value.length; i++) value[i] = pick(ALL);
        for (int i = value.length - 1; i > 0; i--) {
            int j = random.nextInt(i + 1);
            char swap = value[i]; value[i] = value[j]; value[j] = swap;
        }
        return new String(value);
    }
    private char pick(String characters) { return characters.charAt(random.nextInt(characters.length())); }
}
