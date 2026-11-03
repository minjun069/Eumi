package com.eumi.backend;

import java.util.UUID;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.core.io.FileSystemResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

import static org.assertj.core.api.Assertions.assertThat;

/** 실제 PostgreSQL에서 SQL 파일을 실행하며 검사 데이터는 트랜잭션 롤백한다. */
@Tag("local-integration")
@ActiveProfiles("local")
@SpringBootTest
@Transactional
class DemoSeedIntegrationTests {
    @Autowired JdbcTemplate jdbc;
    @Autowired PasswordEncoder passwords;

    private void runSeeds() {
        var populator = new ResourceDatabasePopulator(
                new FileSystemResource("../db/seed/R__02_organization.sql"),
                new FileSystemResource("../db/seed/R__03_demo_member.sql"));
        populator.setSqlScriptEncoding("UTF-8");
        populator.execute(jdbc.getDataSource());
    }

    @Test
    void repeatedSeedDoesNotDuplicateOrganizationsOrMembers() {
        runSeeds();
        var first = jdbc.queryForList("SELECT org_id, email_normalized, password_hash, name, withdrawn_at FROM member "
                + "WHERE email_normalized IN ('demo1@demo-gangnam.eumi.test', 'demo2@demo-gangnam.eumi.test', "
                + "'demo1@demo-chuncheon.eumi.test', 'demo2@demo-chuncheon.eumi.test') ORDER BY email_normalized");
        assertThat(first.size()).isEqualTo(4);
        int organizations = jdbc.queryForObject("SELECT count(*) FROM organization WHERE official_domain "
                + "IN ('demo-gangnam.eumi.test', 'demo-chuncheon.eumi.test')", Integer.class);
        runSeeds();
        var second = jdbc.queryForList("SELECT org_id, email_normalized, password_hash, name, withdrawn_at FROM member "
                + "WHERE email_normalized IN ('demo1@demo-gangnam.eumi.test', 'demo2@demo-gangnam.eumi.test', "
                + "'demo1@demo-chuncheon.eumi.test', 'demo2@demo-chuncheon.eumi.test') ORDER BY email_normalized");
        assertThat(first.equals(second)).isTrue();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM organization WHERE official_domain "
                + "IN ('demo-gangnam.eumi.test', 'demo-chuncheon.eumi.test')", Integer.class)).isEqualTo(organizations);
        assertThat(first.stream().allMatch(row -> row.get("password_hash").toString().startsWith("{pbkdf2}"))).isTrue();
        assertThat(first.stream().map(row -> row.get("password_hash")).distinct().count()).isEqualTo(4);
    }

    @Test
    void repeatedSeedPreservesChangedPasswordProfileAndWithdrawal() {
        runSeeds();
        String changedHash = passwords.encode(UUID.randomUUID().toString());
        jdbc.update("UPDATE member SET password_hash = ?, name = '보존할 프로필', withdrawn_at = now() "
                + "WHERE email_normalized = 'demo1@demo-gangnam.eumi.test'", changedHash);
        runSeeds();
        var member = jdbc.queryForMap("SELECT password_hash, name, withdrawn_at FROM member "
                + "WHERE email_normalized = 'demo1@demo-gangnam.eumi.test'");
        assertThat(changedHash.equals(member.get("password_hash"))).isTrue();
        assertThat(member.get("name")).isEqualTo("보존할 프로필");
        assertThat(member.get("withdrawn_at") != null).isTrue();
    }
}
