package com.eumi.backend;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

import com.eumi.backend.auth.login.AuthService;
import com.eumi.backend.auth.login.LoginRequest;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;

/** 실제 DB 조회·PBKDF2를 사용하고, 암호 비교 시점의 커넥션 반환 경계를 관찰한다. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest
class AuthTransactionIntegrationTests {
    @Autowired JdbcTemplate jdbc;
    @Autowired AuthService auth;
    @MockitoSpyBean PasswordEncoder passwords;

    @Test
    void passwordComparisonRunsAfterJdbcLookupWithoutBoundTransactionOrConnection() {
        String email = "a1-transaction-" + UUID.randomUUID() + "@eumi.test";
        String password = UUID.randomUUID().toString();
        long orgId = jdbc.queryForObject("""
                INSERT INTO organization(org_name, jurisdiction_sigungu_code, official_domain)
                VALUES ('A1 transaction regression', '11680', 'eumi.test') RETURNING org_id
                """, Long.class);
        try {
            long memberId = jdbc.queryForObject("""
                    INSERT INTO member(org_id, email_normalized, name, password_hash)
                    VALUES (?, ?, '검사용 회원', ?) RETURNING member_id
                    """, Long.class, orgId, email, passwords.encode(password));
            var compared = new AtomicBoolean();
            doAnswer(invocation -> {
                compared.set(true);
                assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
                assertThat(TransactionSynchronizationManager.hasResource(jdbc.getDataSource())).isFalse();
                return invocation.callRealMethod();
            }).when(passwords).matches(anyString(), anyString());

            assertThat(auth.authenticate(new LoginRequest(email, password)).memberId()).isEqualTo(memberId);
            assertThat(compared.get()).isTrue();
        } finally {
            jdbc.update("DELETE FROM member WHERE org_id = ? AND email_normalized = ?", orgId, email);
            jdbc.update("DELETE FROM organization WHERE org_id = ? AND org_name = 'A1 transaction regression'", orgId);
        }
    }
}
