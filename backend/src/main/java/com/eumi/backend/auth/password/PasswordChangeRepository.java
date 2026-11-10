package com.eumi.backend.auth.password;

import java.time.*;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class PasswordChangeRepository {
    private final JdbcTemplate jdbc;
    public PasswordChangeRepository(JdbcTemplate jdbc) {this.jdbc=jdbc;}
    public record Account(long orgId,String hash,Instant temporaryExpiresAt,boolean withdrawn) {
        public boolean temporaryExpired(Instant now) {return temporaryExpiresAt!=null && !temporaryExpiresAt.isAfter(now);}
        @Override public String toString() {return "PasswordChangeAccount[redacted]";}
    }
    public Optional<Account> account(long member,boolean lock) {
        return jdbc.query("SELECT org_id,password_hash,temp_password_expires_at,withdrawn_at FROM public.member WHERE member_id=?"
                +(lock ? " FOR UPDATE" : ""),(rs,row)->{
            var expiry=rs.getObject("temp_password_expires_at",OffsetDateTime.class);
            return new Account(rs.getLong("org_id"),rs.getString("password_hash"),expiry==null ? null : expiry.toInstant(),rs.getObject("withdrawn_at")!=null);
        },member).stream().findFirst();
    }
    public void lockOrganization(long org) {
        jdbc.queryForObject("SELECT org_id FROM public.organization WHERE org_id=? FOR UPDATE",Long.class,org);
    }
    public boolean lockCurrentSession(long member,String session,Instant now) {
        return !jdbc.queryForList("""
                SELECT primary_id FROM public.spring_session WHERE principal_name=? AND session_id=? AND expiry_time>? FOR UPDATE
                """,Long.toString(member),session,now.toEpochMilli()).isEmpty();
    }
    public void changeHash(long member,String hash) {
        jdbc.update("UPDATE public.member SET password_hash=?,temp_password_expires_at=NULL,updated_at=now() WHERE member_id=?",hash,member);
    }
    public void deleteOtherSessions(long member,String currentSession) {
        // SessionRepository 개별 삭제 대신 같은 업무 트랜잭션에 참여하는 SQL로 폐기한다.
        jdbc.update("DELETE FROM public.spring_session WHERE principal_name=? AND session_id<>?",Long.toString(member),currentSession);
    }
    public void deleteAllSessions(long member) {
        jdbc.update("DELETE FROM public.spring_session WHERE principal_name=?",Long.toString(member));
    }
}
