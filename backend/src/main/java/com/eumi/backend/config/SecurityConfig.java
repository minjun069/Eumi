package com.eumi.backend.config;

import java.util.List;

import com.eumi.backend.auth.session.PasswordChangeRequiredFilter;
import com.eumi.backend.common.error.ApiErrorWriter;
import com.eumi.backend.common.security.ApiAccessDeniedHandler;
import com.eumi.backend.common.security.ApiAuthenticationEntryPoint;
import jakarta.servlet.DispatcherType;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.AnonymousAuthenticationFilter;
import org.springframework.security.web.authentication.session.ChangeSessionIdAuthenticationStrategy;
import org.springframework.security.web.authentication.session.CompositeSessionAuthenticationStrategy;
import org.springframework.security.web.authentication.session.SessionAuthenticationStrategy;
import org.springframework.security.web.context.DelegatingSecurityContextRepository;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.security.web.context.RequestAttributeSecurityContextRepository;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.security.web.csrf.CsrfAuthenticationStrategy;

@Configuration(proxyBeanMethods = false)
public class SecurityConfig {
    @Bean
    CookieCsrfTokenRepository csrfTokenRepository(
            @Value("${server.servlet.session.cookie.secure:false}") boolean secure) {
        var repository = CookieCsrfTokenRepository.withHttpOnlyFalse();
        repository.setCookieCustomizer(cookie -> cookie.path("/").httpOnly(false).sameSite("Lax").secure(secure));
        return repository;
    }

    @Bean
    SecurityContextRepository securityContextRepository() {
        return new DelegatingSecurityContextRepository(
                new RequestAttributeSecurityContextRepository(), new HttpSessionSecurityContextRepository());
    }

    @Bean
    SessionAuthenticationStrategy sessionAuthenticationStrategy(CookieCsrfTokenRepository csrfRepository) {
        return new CompositeSessionAuthenticationStrategy(List.of(
                new ChangeSessionIdAuthenticationStrategy(), new CsrfAuthenticationStrategy(csrfRepository)));
    }

    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http, CookieCsrfTokenRepository csrfRepository,
            SecurityContextRepository contextRepository, SessionAuthenticationStrategy sessionStrategy,
            ApiAuthenticationEntryPoint entryPoint, ApiAccessDeniedHandler deniedHandler,
            ApiErrorWriter errorWriter) throws Exception {
        http
            .httpBasic(basic -> basic.disable())
            .formLogin(form -> form.disable())
            .logout(logout -> logout.disable())
            .requestCache(cache -> cache.disable())
            .securityContext(context -> context.securityContextRepository(contextRepository).requireExplicitSave(true))
            .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.IF_REQUIRED)
                    .sessionAuthenticationStrategy(sessionStrategy))
            // Security 7.1의 내장 SPA 처리기가 raw 쿠키 헤더와 XOR 처리를 구분한다.
            .csrf(csrf -> csrf.spa().csrfTokenRepository(csrfRepository))
            .exceptionHandling(errors -> errors.authenticationEntryPoint(entryPoint).accessDeniedHandler(deniedHandler))
            .authorizeHttpRequests(auth -> auth
                    .dispatcherTypeMatchers(DispatcherType.ERROR).permitAll()
                    .requestMatchers(HttpMethod.GET, "/health", "/auth/csrf", "/organizations").permitAll()
                    .requestMatchers(HttpMethod.POST, "/auth/login", "/auth/logout", "/auth/temp-password",
                            "/signup/email-verifications", "/signup/email-verifications/verify", "/members").permitAll()
                    .anyRequest().authenticated())
            .addFilterAfter(new PasswordChangeRequiredFilter(errorWriter), AnonymousAuthenticationFilter.class);
        return http.build();
    }
}
