package com.eumi.backend.auth.password;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class TempPasswordRepository {
    private static final String SELECT = "SELECT member_id,email_normalized,name,temp_password_expires_at,withdrawn_at FROM public.member";
    private final JdbcTemplate jdbc;
    public TempPasswordRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Optional<Member> findByEmail(String email) { return find(" WHERE email_normalized=?", email); }
    public Optional<Member> lockMember(long memberId) { return find(" WHERE member_id=? FOR UPDATE", memberId); }
    private Optional<Member> find(String condition, Object value) {
        return jdbc.query(SELECT + condition, (rs, row) -> {
            var expires = rs.getObject("temp_password_expires_at", OffsetDateTime.class);
            return new Member(rs.getLong("member_id"), rs.getString("email_normalized"), rs.getString("name"),
                    expires == null ? null : expires.toInstant(), rs.getObject("withdrawn_at") != null);
        }, value).stream().findFirst();
    }
    public void replacePassword(long memberId, String hash, Instant expires, Instant now) {
        jdbc.update("UPDATE public.member SET password_hash=?,temp_password_expires_at=?,updated_at=? WHERE member_id=?",
                hash, expires.atOffset(ZoneOffset.UTC), now.atOffset(ZoneOffset.UTC), memberId);
    }
    public record Member(long memberId, String email, String name, Instant temporaryExpiresAt, boolean withdrawn) {
        public boolean eligible(TempPasswordRequest input, Instant now) {
            return !withdrawn && email.equals(input.email()) && name.equals(input.name())
                    && (temporaryExpiresAt == null || !temporaryExpiresAt.isAfter(now));
        }
        @Override public String toString() { return "TempPasswordMember[redacted]"; }
    }
}
