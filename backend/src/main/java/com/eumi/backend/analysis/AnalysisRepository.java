package com.eumi.backend.analysis;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

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
                       bg_score, bg_grade, bh_score, bh_grade, risk_grade, quick_insight, insight_generated_at
                FROM public.v_region_insight WHERE adm_cd10 = ? AND period_start = ?
                """, (rs, row) -> {
                    var generated = rs.getObject("insight_generated_at", OffsetDateTime.class);
                    return new InsightRow(rs.getString("adm_cd10"), rs.getString("dong_name"),
                            rs.getString("sigungu_code"), rs.getString("sigungu_name"),
                            rs.getBigDecimal("bg_score"), rs.getObject("bg_grade", Integer.class),
                            rs.getBigDecimal("bh_score"), rs.getObject("bh_grade", Integer.class),
                            rs.getObject("risk_grade", Integer.class), rs.getString("quick_insight"),
                            generated == null ? null : generated.toInstant());
                }, dong, month).stream().findFirst();
    }

    public Optional<ReportRow> report(String dong, LocalDate month) {
        // 분석 결과와 보고서 부재를 한 번의 SELECT로 구분한다. 조회는 생성을 요청하지 않는다.
        return jdbc.query("""
                SELECT i.adm_cd10 AS report_dong, i.quick_insight,
                       i.graph_1, i.desc_1, i.graph_2, i.desc_2, i.graph_3, i.desc_3, i.generated_at
                FROM public.region_result r
                LEFT JOIN public.region_insight_report i
                  ON i.adm_cd10 = r.adm_cd10 AND i.period_start = r.period_start
                 AND i.result_updated_at = r.updated_at
                WHERE r.adm_cd10 = ? AND r.period_start = ?
                """, (rs, row) -> {
                    var generated = rs.getObject("generated_at", OffsetDateTime.class);
                    return new ReportRow(rs.getString("report_dong") != null, rs.getString("quick_insight"),
                            List.of(new AnalysisDtos.ReportGraph(rs.getString("graph_1"), rs.getString("desc_1")),
                                    new AnalysisDtos.ReportGraph(rs.getString("graph_2"), rs.getString("desc_2")),
                                    new AnalysisDtos.ReportGraph(rs.getString("graph_3"), rs.getString("desc_3"))),
                            generated == null ? null : generated.toInstant());
                }, dong, month).stream().findFirst();
    }

    @Transactional(readOnly = true)
    public List<String> reportTargets(LocalDate month) {
        return jdbc.query("SELECT DISTINCT adm_cd10 FROM public.region_result WHERE period_start = ? ORDER BY adm_cd10",
                (rs, row) -> rs.getString(1), month);
    }

    public record InsightRow(String dongCode, String dongName, String sigunguCode, String sigunguName,
            BigDecimal bgScore, Integer bgGrade, BigDecimal bhScore, Integer bhGrade, Integer riskGrade,
            String quickInsight, Instant generatedAt) { }
    public record ReportRow(boolean present, String quickInsight, List<AnalysisDtos.ReportGraph> graphs, Instant generatedAt) { }
}
