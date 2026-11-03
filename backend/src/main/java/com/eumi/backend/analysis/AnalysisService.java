package com.eumi.backend.analysis;

import java.time.LocalDate;
import com.eumi.backend.auth.login.AuthService;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional(readOnly = true)
public class AnalysisService {
    private static final Logger log = LoggerFactory.getLogger(AnalysisService.class);
    private final AnalysisRepository repository;
    private final AuthService auth;
    private final SavedReportReader reports;

    public AnalysisService(AnalysisRepository repository, AuthService auth, SavedReportReader reports) {
        this.repository = repository;
        this.auth = auth;
        this.reports = reports;
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
        if (row.summary() != null || row.generatedAt() != null) {
            if (row.summary() == null || row.summary().isEmpty() || row.generatedAt() == null
                    || row.summary().stream().anyMatch(s -> s == null || s.isEmpty())) {
                throw invalidSavedData(dongCode, month);
            }
            insight = new AnalysisDtos.Insight(row.summary(), row.generatedAt());
        }
        return new AnalysisDtos.DongInsightData(row.dongCode(), row.dongName(), row.sigunguCode(), row.sigunguName(), month,
                new AnalysisDtos.RiskValue(row.bgScore(), row.bgGrade()),
                new AnalysisDtos.RiskValue(row.bhScore(), row.bhGrade()), insight, row.riskGrade());
    }

    public AnalysisDtos.InsightReportData report(long memberId, String dongCode, String month) {
        requireUser(memberId);
        var row = repository.report(dongCode, firstDay(month)).orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND));
        if (row.content() == null && row.generatedAt() == null) return new AnalysisDtos.InsightReportData(null);
        try {
            return new AnalysisDtos.InsightReportData(reports.read(row.content(), row.generatedAt()));
        } catch (IllegalArgumentException ex) {
            throw invalidSavedData(dongCode, month);
        }
    }

    private void requireUser(long memberId) {
        if (auth.currentUser(memberId).mustChangePassword()) throw new ApiException(ErrorCode.PASSWORD_CHANGE_REQUIRED);
        // 분석은 로그인 회원 전체에 공개한다. 기관의 관할은 첫 화면 기본값이며 조회 제한이 아니다.
    }

    private LocalDate firstDay(String month) { return LocalDate.parse(month + "-01"); }
    private boolean grade(Integer value) { return value != null && value >= 1 && value <= 5; }

    private ApiException invalidSavedData(String dong, String month) {
        log.warn("Invalid saved analysis data dongCode={} month={}", dong, month);
        return new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
    }
}
