package com.eumi.backend.auth.session;

import java.io.IOException;

import com.eumi.backend.common.error.ApiErrorWriter;
import com.eumi.backend.common.error.ErrorCode;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/** 제한 상태의 실제 판정은 A1/A3가 담당하고, 세션에 설정된 제한은 이 경계에서 적용한다. */
public class PasswordChangeRequiredFilter extends OncePerRequestFilter {
    private final ApiErrorWriter writer;

    public PasswordChangeRequiredFilter(ApiErrorWriter writer) { this.writer = writer; }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
            FilterChain chain) throws ServletException, IOException {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.isAuthenticated()
                && authentication.getPrincipal() instanceof SessionPrincipal principal
                && principal.mustChangePassword() && !allowed(request)) {
            writer.write(request, response, ErrorCode.PASSWORD_CHANGE_REQUIRED);
            return;
        }
        chain.doFilter(request, response);
    }

    private boolean allowed(HttpServletRequest request) {
        String path = request.getRequestURI().substring(request.getContextPath().length());
        return switch (request.getMethod()) {
            case "GET" -> path.equals("/health") || path.equals("/auth/csrf") || path.equals("/auth/me");
            case "POST" -> path.equals("/auth/logout");
            case "PUT" -> path.equals("/members/me/password");
            default -> false;
        };
    }
}
