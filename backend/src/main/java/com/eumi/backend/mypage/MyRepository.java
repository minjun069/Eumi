package com.eumi.backend.mypage;

import com.eumi.backend.common.error.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class MyRepository {
    private static final Logger log=LoggerFactory.getLogger(MyRepository.class);
    private final JdbcTemplate jdbc;
    public MyRepository(JdbcTemplate jdbc) {this.jdbc=jdbc;}

    public MyDtos.MyInfo info(long member) {
        var rows=jdbc.query("""
                SELECT m.member_id,m.name,m.email_normalized,m.title,m.phone,o.org_name,o.jurisdiction_sigungu_code,
                sd.sido_name,sg.sigungu_name FROM public.member m JOIN public.organization o ON o.org_id=m.org_id
                LEFT JOIN public.v_sigungu sg ON sg.sigungu_code=o.jurisdiction_sigungu_code
                LEFT JOIN public.v_sido sd ON sd.sido_code=left(o.jurisdiction_sigungu_code,2)
                WHERE m.member_id=? AND m.withdrawn_at IS NULL
                """,(rs,row)->{
            String sido=rs.getString("sido_name"),sigungu=rs.getString("sigungu_name");
            if(sido==null || sido.isBlank() || sigungu==null || sigungu.isBlank()) {
                log.warn("Missing my-info jurisdiction mapping memberId={} sigunguCode={}",member,rs.getString("jurisdiction_sigungu_code"));
                throw new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
            }
            return new MyDtos.MyInfo(rs.getString("name"),rs.getString("email_normalized"),rs.getString("org_name"),
                    sido+" "+sigungu,rs.getString("title"),rs.getString("phone"));
        },member);
        if(rows.isEmpty())throw new ApiException(ErrorCode.UNAUTHENTICATED);
        if(rows.size()!=1) {
            log.warn("Ambiguous my-info jurisdiction mapping memberId={}",member);
            throw new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
        }
        return rows.getFirst();
    }
    public void lockOrganization(long org) {
        jdbc.queryForObject("SELECT org_id FROM public.organization WHERE org_id=? FOR UPDATE",Long.class,org);
    }
    public void lockMember(long org,long member) {
        jdbc.query("SELECT member_id FROM public.member WHERE org_id=? AND member_id=? FOR UPDATE",(rs,row)->rs.getLong(1),org,member);
    }
    public void patch(long member,MyDtos.Patch patch) {
        // CASE를 사용해 생략(false)과 명시적 null(true)을 구분한다. 갱신 후 MyInfo 전체를 재조회한다.
        jdbc.update("""
                UPDATE public.member SET title=CASE WHEN ? THEN ? ELSE title END,
                phone=CASE WHEN ? THEN ? ELSE phone END,updated_at=now() WHERE member_id=? AND withdrawn_at IS NULL
                """,patch.titlePresent(),patch.title(),patch.phonePresent(),patch.phone(),member);
    }
}
