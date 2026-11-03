package com.eumi.backend.analysis;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class AnalysisRepository {
    private final JdbcTemplate jdbc;

    public AnalysisRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public boolean sigunguExists(String code) {
        return Boolean.TRUE.equals(jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM public.dim_region WHERE left(adm_cd10, 5) = ?)", Boolean.class, code));
    }

    public List<String> months(String code) {
        return jdbc.query("""
                SELECT DISTINCT period_start FROM public.region_result
                WHERE left(adm_cd10, 5) = ? ORDER BY period_start
                """, (rs, row) -> rs.getObject(1, LocalDate.class).toString().substring(0, 7), code);
    }

    public Optional<InsightRow> insight(String dong, LocalDate month) {
        return jdbc.query("""
                SELECT adm_cd10, dong_name, sigungu_code, sigungu_name,
                       bg_score, bg_grade, bh_score, bh_grade, risk_grade, summary_lines, insight_generated_at
                FROM public.v_region_insight WHERE adm_cd10 = ? AND period_start = ?
                """, (rs, row) -> {
                    var array = rs.getArray("summary_lines");
                    List<String> summary = null;
                    if (array != null) {
                        try { summary = Arrays.asList((String[]) array.getArray()); }
                        finally { array.free(); }
                    }
                    var generated = rs.getObject("insight_generated_at", OffsetDateTime.class);
                    return new InsightRow(rs.getString("adm_cd10"), rs.getString("dong_name"),
                            rs.getString("sigungu_code"), rs.getString("sigungu_name"),
                            rs.getBigDecimal("bg_score"), rs.getObject("bg_grade", Integer.class),
                            rs.getBigDecimal("bh_score"), rs.getObject("bh_grade", Integer.class),
                            rs.getObject("risk_grade", Integer.class), summary,
                            generated == null ? null : generated.toInstant());
                }, dong, month).stream().findFirst();
    }

    public Optional<ReportRow> report(String dong, LocalDate month) {
        // 분석 결과와 보고서 부재를 한 번의 SELECT로 구분한다. 조회는 생성을 요청하지 않는다.
        return jdbc.query("""
                SELECT i.report::text, i.generated_at FROM public.region_result r
                LEFT JOIN public.region_insight_report i
                  ON i.adm_cd10 = r.adm_cd10 AND i.period_start = r.period_start
                WHERE r.adm_cd10 = ? AND r.period_start = ?
                """, (rs, row) -> {
                    var generated = rs.getObject("generated_at", OffsetDateTime.class);
                    return new ReportRow(rs.getString("report"), generated == null ? null : generated.toInstant());
                }, dong, month).stream().findFirst();
    }

    public record InsightRow(String dongCode, String dongName, String sigunguCode, String sigunguName,
            BigDecimal bgScore, Integer bgGrade, BigDecimal bhScore, Integer bhGrade, Integer riskGrade,
            List<String> summary, Instant generatedAt) { }
    public record ReportRow(String content, Instant generatedAt) { }
}
