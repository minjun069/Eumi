package com.eumi.backend.auth.session;

import java.io.Serial;
import java.io.Serializable;
import java.security.Principal;

/** 비밀번호·이메일 원문을 포함하지 않는 JDBC 세션 principal. */
public record SessionPrincipal(long memberId, boolean mustChangePassword) implements Principal, Serializable {
    @Serial
    private static final long serialVersionUID = 1L;

    public SessionPrincipal {
        if (memberId < 1) throw new IllegalArgumentException("memberId must be positive");
    }

    @Override
    public String getName() { return Long.toString(memberId); }
}
