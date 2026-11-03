package com.eumi.backend.auth.login;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.Optional;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class AuthMemberRepository {
    private static final String SELECT = """
            SELECT m.member_id, m.org_id, m.email_normalized, m.name, m.title, m.password_hash,
                   m.temp_password_expires_at, m.withdrawn_at, o.org_name, o.jurisdiction_sigungu_code
            FROM member m JOIN organization o ON o.org_id = m.org_id
            """;
    private final JdbcTemplate jdbc;

    public AuthMemberRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Optional<Member> findByEmail(String email) {
        return jdbc.query(SELECT + " WHERE m.email_normalized = ?", this::map, email).stream().findFirst();
    }

    public Optional<Member> findById(long memberId) {
        return jdbc.query(SELECT + " WHERE m.member_id = ?", this::map, memberId).stream().findFirst();
    }

    private Member map(ResultSet rs, int row) throws SQLException {
        var expires = rs.getObject("temp_password_expires_at", OffsetDateTime.class);
        var sigungu = rs.getString("jurisdiction_sigungu_code");
        return new Member(new LoginUser(rs.getLong("member_id"), rs.getString("name"),
                rs.getString("org_name"), rs.getString("title"), sigungu.substring(0, 2), sigungu,
                expires != null, rs.getString("email_normalized"), rs.getLong("org_id")),
                rs.getString("password_hash"), expires == null ? null : expires.toInstant(),
                rs.getObject("withdrawn_at") != null);
    }

    record Member(LoginUser user, String passwordHash, Instant temporaryPasswordExpiresAt, boolean withdrawn) {
        boolean canAuthenticate(Instant now) {
            return !withdrawn && (temporaryPasswordExpiresAt == null || temporaryPasswordExpiresAt.isAfter(now));
        }

        @Override
        public String toString() { return "Member[redacted]"; }
    }
}
