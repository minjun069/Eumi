package com.eumi.backend.analysis;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import com.eumi.backend.auth.login.AuthService;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional(readOnly = true)
public class AnalysisService {
    private static final Logger log = LoggerFactory.getLogger(AnalysisService.class);
    private static final Set<String> REPORT_SHEETS = Set.of("EmbedDetailV01", "EmbedDetailV02", "EmbedDetailV03", "EmbedDetailV04",
            "EmbedDetailV05", "EmbedDetailV06", "EmbedDetailV07", "EmbedDetailV08");
    private final AnalysisRepository repository;
    private final AuthService auth;

    public AnalysisService(AnalysisRepository repository, AuthService auth) {
        this.repository = repository;
        this.auth = auth;
    }

    public AnalysisDtos.LoadedMonths months(long memberId, String sigunguCode) {
        requireUser(memberId);
        if (!repository.sigunguExists(sigunguCode)) throw new ApiException(ErrorCode.NOT_FOUND);
        return new AnalysisDtos.LoadedMonths(repository.months(sigunguCode));
    }

    public AnalysisDtos.DongInsightData insight(long memberId, String dongCode, String month) {
        requireUser(memberId);
        var row = repository.insight(dongCode, firstDay(month)).orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND));
        if (row.dongName() == null || row.sigunguName() == null || row.bgScore() == null || row.bhScore() == null
                || !grade(row.bgGrade()) || !grade(row.bhGrade()) || !grade(row.riskGrade())) {
            throw invalidSavedData(dongCode, month);
        }
        AnalysisDtos.Insight insight = null;
        // 1단계 view에는 옛 generated_at이 남아 있어도 quick_insight가 NULL일 수 있다.
        if (row.quickInsight() != null) {
            if (row.generatedAt() == null) {
                throw invalidSavedData(dongCode, month);
            }
            insight = new AnalysisDtos.Insight(List.of(row.quickInsight()), row.generatedAt());
        }
        return new AnalysisDtos.DongInsightData(row.dongCode(), row.dongName(), row.sigunguCode(), row.sigunguName(), month,
                new AnalysisDtos.RiskValue(row.bgScore(), row.bgGrade()),
                new AnalysisDtos.RiskValue(row.bhScore(), row.bhGrade()), insight, row.riskGrade());
    }

    public AnalysisDtos.InsightReportData report(long memberId, String dongCode, String month) {
        requireUser(memberId);
        var row = repository.report(dongCode, firstDay(month)).orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND));
        if (!row.present()) return new AnalysisDtos.InsightReportData(null);
        var graphs = new ArrayList<AnalysisDtos.ReportGraph>();
        for (int slot = 0; slot < row.graphs().size(); slot++) {
            var graph = row.graphs().get(slot);
            if (graph.sheet() == null) continue;
            if (!REPORT_SHEETS.contains(graph.sheet())) {
                // 보고서 본문/임의 sheet 값은 로그에 남기지 않는다.
                log.warn("Saved report graph skipped: unsupported sheet requestId={} month={} slot={}",
                        MDC.get("requestId"), month, slot + 1);
                continue;
            }
            graphs.add(new AnalysisDtos.ReportGraph(graph.sheet(), graph.description()));
        }
        if (graphs.isEmpty() && row.quickInsight() == null) return new AnalysisDtos.InsightReportData(null);
        return new AnalysisDtos.InsightReportData(new AnalysisDtos.Report(row.quickInsight(), List.copyOf(graphs), row.generatedAt()));
    }

    private void requireUser(long memberId) {
        if (auth.currentUser(memberId).mustChangePassword()) throw new ApiException(ErrorCode.PASSWORD_CHANGE_REQUIRED);
        // 분석은 로그인 회원 전체에 공개한다. 기관의 관할은 첫 화면 기본값이며 조회 제한이 아니다.
    }

    private LocalDate firstDay(String month) { return LocalDate.parse(month + "-01"); }
    private boolean grade(Integer value) { return value != null && value >= 1 && value <= 5; }

    private ApiException invalidSavedData(String dong, String month) {
        log.warn("Invalid saved analysis data requestId={} month={} status=500", MDC.get("requestId"), month);
        return new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
    }
}
