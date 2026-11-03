package com.eumi.backend.reference;

import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ReferenceDataRepository {
    private final JdbcTemplate jdbc;

    public ReferenceDataRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public List<ReferenceDataDtos.SidoItem> sidos() {
        return jdbc.query("SELECT sido_code, sido_name FROM v_sido ORDER BY sido_code",
                (rs, row) -> new ReferenceDataDtos.SidoItem(rs.getString("sido_code"), rs.getString("sido_name")));
    }

    public boolean sidoExists(String sidoCode) {
        return Boolean.TRUE.equals(jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM v_sido WHERE sido_code = ?)", Boolean.class, sidoCode));
    }

    public List<ReferenceDataDtos.SigunguItem> sigungus(String sidoCode) {
        return jdbc.query("SELECT sigungu_code, sigungu_name FROM v_sigungu WHERE sido_code = ? ORDER BY sigungu_code",
                (rs, row) -> new ReferenceDataDtos.SigunguItem(rs.getString("sigungu_code"), rs.getString("sigungu_name")), sidoCode);
    }

    public boolean sigunguExists(String sigunguCode) {
        return Boolean.TRUE.equals(jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM v_sigungu WHERE sigungu_code = ?)", Boolean.class, sigunguCode));
    }

    public List<ReferenceDataDtos.DongItem> dongs(String sigunguCode) {
        return jdbc.query("SELECT adm_cd10, adm_nm FROM dim_region WHERE left(adm_cd10, 5) = ? ORDER BY adm_cd10",
                (rs, row) -> new ReferenceDataDtos.DongItem(rs.getString("adm_cd10"), rs.getString("adm_nm")), sigunguCode);
    }

    public List<ReferenceDataDtos.MemberOption> activeMembers(long orgId) {
        return jdbc.query("""
                SELECT member_id, name, title FROM member
                WHERE org_id = ? AND withdrawn_at IS NULL
                ORDER BY name, member_id
                """, (rs, row) -> new ReferenceDataDtos.MemberOption(
                rs.getLong("member_id"), rs.getString("name"), rs.getString("title")), orgId);
    }
}
