package com.eumi.backend.analysis;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

public final class AnalysisDtos {
    private AnalysisDtos() { }

    public record LoadedMonths(List<String> months) { }
    public record RiskValue(BigDecimal score, int stage) { }
    public record Insight(List<String> summary, Instant generatedAt) { }
    public record DongInsightData(String dongCode, String dongName, String sigunguCode, String sigunguName,
            String month, RiskValue background, RiskValue behavior, Insight insight, int riskGrade) { }
    public record ReportGraph(String sheet, String description) { }
    public record Report(String quickInsight, List<ReportGraph> graphs, Instant generatedAt) { }
    public record InsightReportData(Report report) { }
}
