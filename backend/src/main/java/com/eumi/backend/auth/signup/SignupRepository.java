package com.eumi.backend.auth.signup;

import java.sql.*;
import java.time.*;
import java.util.*;
import com.eumi.backend.common.error.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class SignupRepository {
    private final JdbcTemplate jdbc;
    public SignupRepository(JdbcTemplate jdbc) {this.jdbc=jdbc;}
    public List<SignupDtos.OrganizationSearchItem> organizations(String keyword) {
        return jdbc.query("""
                SELECT o.org_id,o.org_name,sd.sido_name,sg.sigungu_name,o.official_domain
                FROM public.organization o
                LEFT JOIN public.v_sigungu sg ON sg.sigungu_code=o.jurisdiction_sigungu_code
                LEFT JOIN public.v_sido sd ON sd.sido_code=left(o.jurisdiction_sigungu_code,2)
                WHERE position(? IN o.org_name)>0 ORDER BY o.org_name,o.org_id LIMIT 20
                """,(rs,row)->{
            String sido=rs.getString(3),sigungu=rs.getString(4);
            if(sido==null || sido.isBlank() || sigungu==null || sigungu.isBlank()) throw new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
            return new SignupDtos.OrganizationSearchItem(rs.getLong(1),rs.getString(2),sido,sigungu,rs.getString(5));
        },keyword);
    }
    public Optional<Organization> organization(long id) {
        return jdbc.query("SELECT org_id,official_domain FROM public.organization WHERE org_id=?",
                (rs,row)->new Organization(rs.getLong(1),rs.getString(2)),id).stream().findFirst();
    }
    public record Organization(long orgId,String officialDomain) { }
    public boolean memberExists(String email) {
        return Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM public.member WHERE email_normalized=?)",Boolean.class,email));
    }
    public Optional<Verification> verification(String email,boolean lock) {
        return jdbc.query("SELECT verification_id,org_id,code_hash,expires_at,failed_attempt_count,verified_at,proof_hash,proof_expires_at,created_at "+
                "FROM public.email_verification WHERE email_normalized=?"+(lock ? " FOR UPDATE" : ""),(rs,row)->new Verification(
                rs.getObject(1,UUID.class),rs.getLong(2),rs.getBytes(3),instant(rs,4),rs.getInt(5),instant(rs,6),rs.getBytes(7),instant(rs,8),instant(rs,9)),email)
                .stream().findFirst();
    }
    public record Verification(UUID id,long orgId,byte[] codeHash,Instant expiresAt,int failedAttempts,
            Instant verifiedAt,byte[] proofHash,Instant proofExpiresAt,Instant createdAt) {
        @Override public String toString() {return "Verification[redacted]";}
    }
    public void replaceVerification(long org,String email,byte[] hash,Instant now,Instant expires) {
        jdbc.update("DELETE FROM public.email_verification WHERE email_normalized=?",email);
        jdbc.update("INSERT INTO public.email_verification(org_id,email_normalized,code_hash,created_at,expires_at,failed_attempt_count) VALUES (?,?,?,?,?,0)",
                org,email,hash,offset(now),offset(expires));
    }
    public void failedAttempt(UUID id) {jdbc.update("UPDATE public.email_verification SET failed_attempt_count=failed_attempt_count+1 WHERE verification_id=?",id);}
    public void verify(UUID id,byte[] proof,Instant now,Instant expires) {
        jdbc.update("UPDATE public.email_verification SET verified_at=?,proof_hash=?,proof_expires_at=? WHERE verification_id=?",
                offset(now),proof,offset(expires),id);
    }
    public long insertMember(SignupDtos.SignupRequest input,String hash,Instant now) {
        return jdbc.queryForObject("INSERT INTO public.member(org_id,email_normalized,name,title,phone,password_hash,created_at,updated_at) "+
                "VALUES (?,?,?,?,?,?,?,?) RETURNING member_id",Long.class,input.orgId(),input.email(),input.name(),input.title(),input.phone(),hash,offset(now),offset(now));
    }
    public void deleteVerification(UUID id) {jdbc.update("DELETE FROM public.email_verification WHERE verification_id=?",id);}
    private static OffsetDateTime offset(Instant time) {return time.atOffset(ZoneOffset.UTC);}
    private static Instant instant(ResultSet rs,int column) throws SQLException {
        var value=rs.getObject(column,OffsetDateTime.class);return value==null ? null : value.toInstant();
    }
}
