package com.eumi.backend.cases;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;

@Repository
public class CaseRepository {
    private final JdbcTemplate jdbc;
    private final NamedParameterJdbcTemplate named;
    private static final Map<String, String> SORTS = Map.of(
            "name", "c.name", "region", "(c.sigungu_name || ' ' || c.dong_name)", "age", "c.age",
            "gender", "c.gender", "firstRegisteredAt", "c.first_registered_at", "lastRecordedAt", "c.last_recorded_at");

    public CaseRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; this.named = new NamedParameterJdbcTemplate(jdbc); }

    public Optional<Access> access(long caseId, long orgId, long memberId, boolean lock) {
        return jdbc.query("""
                SELECT c.org_id, EXISTS(SELECT 1 FROM public.case_manager m WHERE m.case_id=c.case_id AND m.member_id=?) AS assigned
                FROM public.case_record c WHERE c.case_id=? AND c.org_id=?
                """ + (lock ? " FOR UPDATE OF c" : ""),
                (rs, row) -> new Access(rs.getLong("org_id"), rs.getBoolean("assigned")), memberId, caseId, orgId).stream().findFirst();
    }
    public record Access(long orgId, boolean assigned) { }

    public void lockOrganization(long orgId) {
        jdbc.queryForObject("SELECT org_id FROM public.organization WHERE org_id=? FOR UPDATE", Long.class, orgId);
    }

    public Set<Long> lockActiveMembers(long orgId, Collection<Long> memberIds) {
        return new HashSet<>(named.query("""
                SELECT member_id, withdrawn_at FROM public.member
                WHERE org_id=:org AND member_id IN (:ids) ORDER BY member_id FOR UPDATE
                """, new MapSqlParameterSource("org", orgId).addValue("ids", memberIds),
                (rs, row) -> rs.getObject("withdrawn_at") == null ? rs.getLong("member_id") : null)
                .stream().filter(Objects::nonNull).toList());
    }

    public boolean dongExists(String dong) {
        return Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM public.dim_region WHERE adm_cd10=?)", Boolean.class, dong));
    }

    public CaseDtos.Page search(long org, long member, CaseDtos.Search s) {
        var parameters = new MapSqlParameterSource("org", org).addValue("member", member);
        var where = new StringBuilder(" FROM public.v_case_summary c JOIN public.case_manager m ON m.case_id=c.case_id "
                + "WHERE c.org_id=:org AND m.member_id=:member");
        add(where, parameters, "sido", "c.sido_code", s.sidoCode(), "=");
        add(where, parameters, "sigungu", "c.sigungu_code", s.sigunguCode(), "=");
        add(where, parameters, "dong", "c.dong_code", s.dongCode(), "=");
        if (!s.ageGroup().equals("전체")) add(where, parameters, "ageGroup", "c.age_group", s.ageGroup(), "=");
        if (!s.gender().equals("전체")) add(where, parameters, "gender", "c.gender", s.gender(), "=");
        add(where, parameters, "regFrom", "c.first_registered_at", s.registeredFrom(), ">=");
        add(where, parameters, "regTo", "c.first_registered_at", s.registeredTo(), "<=");
        add(where, parameters, "recFrom", "c.last_recorded_at", s.recordedFrom(), ">=");
        add(where, parameters, "recTo", "c.last_recorded_at", s.recordedTo(), "<=");
        if (!s.keyword().isEmpty()) {
            // POSITION은 %, _, 역슬래시도 문자 그대로 비교한다.
            where.append(" AND (position(:keyword IN c.name)>0 OR position(:keyword IN c.management_no)>0)");
            parameters.addValue("keyword", s.keyword());
        }
        long count = named.queryForObject("SELECT count(*)" + where, parameters, Long.class);
        long pages = count == 0 ? 0 : (count - 1) / s.size() + 1;
        long page = pages == 0 ? 1 : Math.min(s.page(), pages);
        String column = SORTS.get(s.sort());
        if (column == null || !Set.of("asc", "desc").contains(s.direction())) throw new ApiException(ErrorCode.VALIDATION_ERROR);
        parameters.addValue("limit", s.size()).addValue("offset", (page - 1) * s.size());
        var items = named.query("SELECT c.*" + where + " ORDER BY " + column + " " + s.direction()
                + " NULLS LAST, c.case_id DESC LIMIT :limit OFFSET :offset", parameters, this::listItem);
        return new CaseDtos.Page(count, page, s.size(), pages, items);
    }

    private void add(StringBuilder sql, MapSqlParameterSource parameters, String key, String column, Object value, String operator) {
        if (value != null) { sql.append(" AND ").append(column).append(operator).append(':').append(key); parameters.addValue(key, value); }
    }

    private CaseDtos.ListItem listItem(ResultSet rs, int row) throws SQLException {
        if (rs.getString("sido_name") == null) throw new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
        return new CaseDtos.ListItem(rs.getLong("case_id"), rs.getString("management_no"), rs.getString("name"),
                rs.getInt("age"), rs.getString("age_group"), rs.getString("gender"), rs.getString("sido_name"),
                rs.getString("sigungu_name"), rs.getString("dong_name"), rs.getObject("first_registered_at", LocalDate.class),
                rs.getObject("last_recorded_at", LocalDate.class));
    }

    public CaseDtos.Detail detail(long caseId) {
        var managers = jdbc.query("""
                SELECT m.member_id, m.name, m.title FROM public.case_manager cm
                JOIN public.member m ON m.member_id=cm.member_id WHERE cm.case_id=? ORDER BY m.name, m.member_id
                """, (rs, row) -> new CaseDtos.Manager(rs.getLong(1), rs.getString(2), rs.getString(3)), caseId);
        return jdbc.queryForObject("SELECT * FROM public.v_case_summary WHERE case_id=?", (rs, row) -> {
            var item = listItem(rs, row);
            return new CaseDtos.Detail(item.caseId(), item.managementNo(), item.name(), item.age(), item.ageGroup(), item.gender(),
                    item.sidoName(), item.sigunguName(), item.dongName(), item.firstRegisteredAt(), item.lastRecordedAt(),
                    rs.getObject("birth_date", LocalDate.class), rs.getString("sido_code"), rs.getString("sigungu_code"),
                    rs.getString("dong_code"), managers);
        }, caseId);
    }

    public List<CaseDtos.Duplicate> duplicates(long org, long member, CaseDtos.DuplicateInput input) {
        return jdbc.query("""
                SELECT c.case_id, c.management_no, c.name FROM public.case_record c
                JOIN public.case_manager cm ON cm.case_id=c.case_id
                WHERE c.org_id=? AND cm.member_id=? AND c.name=? AND c.birth_date=? AND (?::bigint IS NULL OR c.case_id<>?)
                ORDER BY c.case_id
                """, (rs, row) -> new CaseDtos.Duplicate(rs.getLong(1), rs.getString(2), rs.getString(3)),
                org, member, input.name(), input.birthDate(), input.excludeCaseId(), input.excludeCaseId());
    }

    public int lastNumber(long org, String year) {
        return jdbc.queryForObject("SELECT coalesce(max(right(management_no,4)::integer),0) FROM public.case_record "
                + "WHERE org_id=? AND left(management_no,4)=?", Integer.class, org, year);
    }
    public String nextNumber(long org, LocalDate registered) {
        return jdbc.queryForObject("SELECT public.next_management_no(?,?)", String.class, org, registered);
    }
    public long insert(long org, String number, CaseDtos.Input input) {
        return jdbc.queryForObject("""
                INSERT INTO public.case_record(org_id,management_no,name,birth_date,gender,dong_code,first_registered_at)
                VALUES (?,?,?,?,?,?,?) RETURNING case_id
                """, Long.class, org, number, input.name(), input.birthDate(), input.gender(), input.dongCode(), input.firstRegisteredAt());
    }
    public void update(long id, CaseDtos.Input input) {
        jdbc.update("""
                UPDATE public.case_record SET name=?,birth_date=?,gender=?,dong_code=?,first_registered_at=?,updated_at=now() WHERE case_id=?
                """, input.name(), input.birthDate(), input.gender(), input.dongCode(), input.firstRegisteredAt(), id);
    }
    public void replaceManagers(long id, Collection<Long> managers) {
        jdbc.update("DELETE FROM public.case_manager WHERE case_id=?", id);
        for (long manager : managers) jdbc.update("INSERT INTO public.case_manager(case_id,member_id) VALUES (?,?)", id, manager);
    }
    public void delete(long id) { jdbc.update("DELETE FROM public.case_record WHERE case_id=?", id); }
}
