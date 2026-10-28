package com.eumi.backend.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

/**
 * 개발 초기용 임시 설정: 로그인 기능이 생기기 전까지 모든 요청을 허용한다.
 * (Spring Security를 넣으면 기본값이 "모든 요청 차단"이라, 이 설정이 없으면 팀원 API 호출이 전부 401이 된다.)
 *
 * TODO(백엔드) 쿠키 로그인 구현 시 docs/decisions/login-sse.md 기준으로 교체한다.
 *   - /health 만 permitAll, 나머지는 authenticated()
 *   - 쿠키 인증이므로 CSRF를 disable 상태로 두지 않는다 (SameSite=Lax + CSRF 토큰 검토)
 *   - CORS는 운영 도메인만 허용
 *   - 실제 개인 정보 데이터를 넣기 전에 반드시 교체한다
 */
@Configuration
public class SecurityConfig {

    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
            .csrf(csrf -> csrf.disable())
            .httpBasic(basic -> basic.disable())
            .formLogin(form -> form.disable())
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/health").permitAll()
                .anyRequest().permitAll());
        return http.build();
    }
}
