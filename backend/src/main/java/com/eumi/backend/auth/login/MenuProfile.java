package com.eumi.backend.auth.login;

public record MenuProfile(long memberId, String name, String orgName, String title,
        String jurisdictionSidoCode, String jurisdictionSigunguCode, boolean mustChangePassword) { }
