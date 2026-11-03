package com.eumi.backend;

import java.util.UUID;
import java.sql.SQLException;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.core.io.FileSystemResource;
import org.springframework.dao.DataAccessException;
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

    @Test
    void seededMembersPointToOrganizationsWithMatchingDomainAndJurisdiction() {
        runSeeds();
        var members = jdbc.queryForList("""
                SELECT m.email_normalized, o.official_domain, o.jurisdiction_sigungu_code
                FROM member m JOIN organization o ON o.org_id = m.org_id
                WHERE m.email_normalized IN ('demo1@demo-gangnam.eumi.test', 'demo2@demo-gangnam.eumi.test',
                    'demo1@demo-chuncheon.eumi.test', 'demo2@demo-chuncheon.eumi.test')
                """);
        assertThat(members.size()).isEqualTo(4);
        for (var member : members) {
            String domain = member.get("email_normalized").toString().split("@", 2)[1];
            assertThat(member.get("official_domain")).isEqualTo(domain);
            assertThat(member.get("jurisdiction_sigungu_code"))
                    .isEqualTo(domain.equals("demo-gangnam.eumi.test") ? "11680" : "51110");
        }
    }

    @Test
    void organizationSeedDoesNotHidePrimaryKeyCollision() {
        // 독립적인 임시 IDENTITY를 사용해 공용 테이블·시퀀스를 건드리지 않는다.
        jdbc.execute("CREATE TEMP TABLE organization (LIKE public.organization INCLUDING ALL) ON COMMIT DROP");
        jdbc.update("""
                INSERT INTO pg_temp.organization(org_id, org_name, jurisdiction_sigungu_code, official_domain)
                VALUES (1, 'PK 충돌 검사용', '11680', 'eumi.test')
                """);
        assertUniqueViolation(this::runSeeds);
    }

    @Test
    void memberSeedIgnoresOnlyEmailConflictAndDoesNotHidePrimaryKeyCollision() {
        jdbc.execute("CREATE TEMP TABLE organization (LIKE public.organization INCLUDING ALL) ON COMMIT DROP");
        jdbc.execute("CREATE TEMP TABLE member (LIKE public.member INCLUDING ALL) ON COMMIT DROP");
        runSeeds();
        jdbc.update("DELETE FROM pg_temp.member");
        // 첫 실행에서 임시 시퀀스는 1~4를 소모했으므로 다음 값 5와 충돌시킨다.
        jdbc.update("""
                INSERT INTO pg_temp.member(member_id, org_id, email_normalized, name, password_hash)
                SELECT 5, org_id, ?, 'PK 충돌 검사용', 'invalid-test-hash'
                FROM pg_temp.organization WHERE official_domain = 'demo-gangnam.eumi.test'
                """, "a1-pk-" + UUID.randomUUID() + "@eumi.test");
        assertUniqueViolation(this::runSeeds);
    }

    private void assertUniqueViolation(Runnable action) {
        try {
            action.run();
            throw new AssertionError("Seed must expose an unexpected primary key collision.");
        } catch (DataAccessException ex) {
            var cause = ex.getMostSpecificCause();
            assertThat(cause instanceof SQLException sql && "23505".equals(sql.getSQLState())).isTrue();
        }
    }
}
