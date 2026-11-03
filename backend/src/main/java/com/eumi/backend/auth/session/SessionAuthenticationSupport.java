package com.eumi.backend.auth.session;

import java.util.List;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.session.SessionAuthenticationStrategy;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.security.web.authentication.logout.SecurityContextLogoutHandler;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.security.web.csrf.CsrfLogoutHandler;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;

@Component
public class SessionAuthenticationSupport {
    private final SecurityContextRepository repository;
    private final SessionAuthenticationStrategy strategy;
    private final CookieCsrfTokenRepository csrf;
    private final boolean secure;

    public SessionAuthenticationSupport(SecurityContextRepository repository, SessionAuthenticationStrategy strategy,
            CookieCsrfTokenRepository csrf, @Value("${server.servlet.session.cookie.secure:false}") boolean secure) {
        this.repository = repository;
        this.strategy = strategy;
        this.csrf = csrf;
        this.secure = secure;
    }

    /** A1의 자격 검증을 통과한 경우에만 호출한다. 이 메서드는 자격 증명을 검증하지 않는다. */
    public void establish(SessionPrincipal principal, HttpServletRequest request, HttpServletResponse response) {
        var authentication = UsernamePasswordAuthenticationToken.authenticated(principal, null,
                List.of(new SimpleGrantedAuthority("ROLE_MEMBER")));
        strategy.onAuthentication(authentication, request, response);
        var context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(authentication);
        SecurityContextHolder.setContext(context);
        repository.saveContext(context, request, response);
    }

    public void logout(HttpServletRequest request, HttpServletResponse response) {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        var handler = new SecurityContextLogoutHandler();
        handler.setSecurityContextRepository(repository);
        handler.logout(request, response, authentication);
        new CsrfLogoutHandler(csrf).logout(request, response, authentication);
        response.addHeader(HttpHeaders.SET_COOKIE, ResponseCookie.from("SESSION", "")
                .path(request.getContextPath().isEmpty() ? "/" : request.getContextPath())
                .httpOnly(true).secure(secure).sameSite("Lax").maxAge(0).build().toString());
    }
}
