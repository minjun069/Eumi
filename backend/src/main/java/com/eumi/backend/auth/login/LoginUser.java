package com.eumi.backend.auth.login;

public record LoginUser(long memberId, String name, String orgName, String title,
        String jurisdictionSidoCode, String jurisdictionSigunguCode, boolean mustChangePassword,
        String email, long orgId) {
    public MenuProfile menuProfile() {
        return new MenuProfile(memberId, name, orgName, title, jurisdictionSidoCode,
                jurisdictionSigunguCode, mustChangePassword);
    }
}
