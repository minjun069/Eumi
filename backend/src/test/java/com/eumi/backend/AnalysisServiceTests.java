package com.eumi.backend;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import com.eumi.backend.analysis.*;
import com.eumi.backend.auth.login.AuthService;
import com.eumi.backend.auth.login.LoginUser;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** DB에 쓸 수 없는 미적재·생성 완료·손상 데이터를 mock으로 검사한다. */
@ExtendWith(MockitoExtension.class)
class AnalysisServiceTests {
    @Mock AnalysisRepository repository;
    @Mock AuthService auth;
    private AnalysisService service;
    private static final String DONG = "1168066000";
    private static final LocalDate MONTH = LocalDate.of(2025, 12, 1);
    private static final Instant GENERATED = Instant.parse("2026-11-03T00:00:00Z");

    @BeforeEach
    void setup() {
        service = new AnalysisService(repository, auth);
        when(auth.currentUser(1)).thenReturn(user(false));
    }

    private LoginUser user(boolean temporary) {
        return new LoginUser(1, "Synthetic", "Synthetic org", null, "11", "11680", temporary, "synthetic@eumi.test", 7);
    }

    @Test
    void existingRegionWithoutResultsReturnsEmptyMonths() {
        when(repository.sigunguExists("11680")).thenReturn(true);
        when(repository.months("11680")).thenReturn(List.of());
        assertThat(service.months(1, "11680").months()).isEmpty();
    }

    @Test
    void missingRegionIs404BeforeLoadingMonths() {
        error(() -> service.months(1, "99999"), ErrorCode.NOT_FOUND);
        verify(repository, never()).months(anyString());
    }

    @Test
    void missingResultIs404ForInsightAndReport() {
        error(() -> service.insight(1, DONG, "2025-12"), ErrorCode.NOT_FOUND);
        error(() -> service.report(1, DONG, "2025-12"), ErrorCode.NOT_FOUND);
    }

    @Test
    void temporaryAccountIsDeniedBeforeReadingAnyAnalysisData() {
        when(auth.currentUser(1)).thenReturn(user(true));
        error(() -> service.months(1, "11680"), ErrorCode.PASSWORD_CHANGE_REQUIRED);
        error(() -> service.insight(1, DONG, "2025-12"), ErrorCode.PASSWORD_CHANGE_REQUIRED);
        error(() -> service.report(1, DONG, "2025-12"), ErrorCode.PASSWORD_CHANGE_REQUIRED);
        verifyNoInteractions(repository);
    }

    @Test
    void scoresGradesAndGeneratedInsightMapWithoutLosingText() {
        when(repository.insight(DONG, MONTH)).thenReturn(Optional.of(row(0, "**Synthetic** summary\nSecond line", GENERATED)));
        var result = service.insight(1, DONG, "2025-12");
        assertThat(result.background().score()).isEqualByComparingTo("24.50");
        assertThat(result.background().stage()).isEqualTo(2);
        assertThat(result.behavior().score()).isEqualByComparingTo("55.13");
        assertThat(result.behavior().stage()).isEqualTo(4);
        assertThat(result.riskGrade()).isEqualTo(3);
        assertThat(result.insight().summary()).containsExactly("**Synthetic** summary\nSecond line");
        assertThat(result.insight().generatedAt()).isEqualTo(GENERATED);
    }

    @ParameterizedTest
    @ValueSource(ints = {1, 2, 3, 4, 5})
    void missingRequiredScoreOrGradeIs500RatherThanInventedValue(int missing) {
        when(repository.insight(DONG, MONTH)).thenReturn(Optional.of(row(missing, null, null)));
        error(() -> service.insight(1, DONG, "2025-12"), ErrorCode.INTERNAL_SERVER_ERROR);
    }

    @Test
    void nullQuickInsightWithOldTimestampIsPendingAndScoresRemainReadable() {
        when(repository.insight(DONG, MONTH)).thenReturn(Optional.of(row(0, null, GENERATED)));
        var result = service.insight(1, DONG, "2025-12");
        assertThat(result.insight()).isNull();
        assertThat(result.background().score()).isEqualByComparingTo("24.50");
    }

    @Test
    void missingGenerationTimestampWithQuickInsightIs500() {
        when(repository.insight(DONG, MONTH)).thenReturn(Optional.of(row(0, "Synthetic quick", null)));
        error(() -> service.insight(1, DONG, "2025-12"), ErrorCode.INTERNAL_SERVER_ERROR);
    }

    @Test
    void reportUsesSlotOrderAndNewFields() {
        var graphs = List.of(new AnalysisDtos.ReportGraph("EmbedDetailV03", "Third"),
                new AnalysisDtos.ReportGraph("EmbedDetailV01", "First"), new AnalysisDtos.ReportGraph("EmbedDetailV08", "Eighth"));
        when(repository.report(DONG, MONTH)).thenReturn(Optional.of(new AnalysisRepository.ReportRow(true, "Quick\nSecond", graphs, GENERATED)));
        var result = service.report(1, DONG, "2025-12").report();
        assertThat(result.quickInsight()).isEqualTo("Quick\nSecond");
        assertThat(result.graphs()).containsExactlyElementsOf(graphs);
        assertThat(result.generatedAt()).isEqualTo(GENERATED);
    }

    @Test
    void unsupportedSheetHidesOnlyTheReport() {
        var graphs = List.of(new AnalysisDtos.ReportGraph("EmbedDetailV09", "Unsupported"),
                new AnalysisDtos.ReportGraph("EmbedDetailV01", "First"), new AnalysisDtos.ReportGraph("EmbedDetailV08", "Eighth"));
        when(repository.report(DONG, MONTH)).thenReturn(Optional.of(new AnalysisRepository.ReportRow(true, "Quick", graphs, GENERATED)));
        when(repository.insight(DONG, MONTH)).thenReturn(Optional.of(row(0, "Quick", GENERATED)));
        assertThat(service.report(1, DONG, "2025-12").report()).isNull();
        assertThat(service.insight(1, DONG, "2025-12").insight().summary()).containsExactly("Quick");
    }

    @Test
    void absentOrStaleReportReturnsExplicitNull() {
        when(repository.report(DONG, MONTH)).thenReturn(Optional.of(new AnalysisRepository.ReportRow(false, null, List.of(), null)));
        assertThat(service.report(1, DONG, "2025-12").report()).isNull();
    }

    private AnalysisRepository.InsightRow row(int missing, String quick, Instant generated) {
        return new AnalysisRepository.InsightRow(DONG, "Synthetic dong", "11680", "Synthetic district",
                missing == 1 ? null : new BigDecimal("24.50"), missing == 2 ? null : 2,
                missing == 3 ? null : new BigDecimal("55.13"), missing == 4 ? null : 4,
                missing == 5 ? null : 3, quick, generated);
    }

    private void error(Runnable action, ErrorCode code) {
        assertThatThrownBy(action::run).isInstanceOfSatisfying(ApiException.class, ex -> assertThat(ex.code()).isEqualTo(code));
    }
}
