package com.eumi.backend.internal;

import java.io.IOException;
import java.util.Collections;
import java.util.List;
import com.eumi.backend.common.error.ApiErrorWriter;
import com.eumi.backend.common.error.ErrorCode;
import com.eumi.backend.common.security.ApiAccessDeniedHandler;
import com.eumi.backend.common.security.ApiAuthenticationEntryPoint;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpMethod;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.AnonymousAuthenticationFilter;
import org.springframework.security.web.context.NullSecurityContextRepository;
import org.springframework.web.filter.OncePerRequestFilter;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(InternalApiProperties.class)
public class InternalSecurityConfiguration {
    @Bean
    @Order(1)
    SecurityFilterChain internalSecurityFilterChain(HttpSecurity http, InternalApiProperties properties, Environment environment,
            ApiErrorWriter writer, ApiAuthenticationEntryPoint entryPoint, ApiAccessDeniedHandler deniedHandler) throws Exception {
        if ("http".equals(environment.getProperty("eumi.ai.mode", "fake"))) properties.requireHttpTokens();
        // /api는 servlet context path다. 내부 서비스 권한은 브라우저 체인과 분리한다.
        http.securityMatcher("/internal/**")
                .httpBasic(basic -> basic.disable()).formLogin(form -> form.disable()).logout(logout -> logout.disable())
                .requestCache(cache -> cache.disable()).csrf(csrf -> csrf.disable())
                .securityContext(context -> context.securityContextRepository(new NullSecurityContextRepository()))
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .exceptionHandling(errors -> errors.authenticationEntryPoint(entryPoint).accessDeniedHandler(deniedHandler))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.POST, "/internal/agent/notifications").hasAuthority("AI")
                        .requestMatchers(HttpMethod.POST, "/internal/analysis/pipeline-completions").hasAuthority("PIPELINE")
                        .requestMatchers(HttpMethod.POST, "/internal/analysis/insight-report-completions").hasAuthority("AI")
                        .anyRequest().denyAll())
                .addFilterBefore(new TokenFilter(properties, writer), AnonymousAuthenticationFilter.class);
        return http.build();
    }

    // Servlet 전역 필터로 등록하지 않는다. 내부 보안 체인에서만 실행한다.
    private static class TokenFilter extends OncePerRequestFilter {
        private final InternalApiProperties properties;
        private final ApiErrorWriter writer;
        TokenFilter(InternalApiProperties properties, ApiErrorWriter writer) { this.properties = properties; this.writer = writer; }
        @Override protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
                throws ServletException, IOException {
            var headers = Collections.list(request.getHeaders("Authorization"));
            String header = headers.size() == 1 ? headers.getFirst() : null;
            String caller = header != null && header.regionMatches(true, 0, "Bearer ", 0, 7)
                    ? properties.caller(header.substring(7)) : null;
            if (caller == null) { writer.write(request, response, ErrorCode.UNAUTHENTICATED); return; }
            var context = SecurityContextHolder.createEmptyContext();
            context.setAuthentication(UsernamePasswordAuthenticationToken.authenticated(caller, null,
                    List.of(new SimpleGrantedAuthority(caller))));
            SecurityContextHolder.setContext(context);
            try { chain.doFilter(request, response); }
            finally { SecurityContextHolder.clearContext(); }
        }
    }
}
