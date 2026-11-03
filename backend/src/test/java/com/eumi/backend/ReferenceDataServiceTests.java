package com.eumi.backend;

import java.util.List;
import com.eumi.backend.auth.login.AuthService;
import com.eumi.backend.auth.login.LoginUser;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import com.eumi.backend.reference.ReferenceDataDtos;
import com.eumi.backend.reference.ReferenceDataRepository;
import com.eumi.backend.reference.ReferenceDataService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

/** 공용 DB를 변경하지 않고 지역 데이터 미적재와 시도 이름 매핑 누락을 검사한다. */
@ExtendWith({MockitoExtension.class, OutputCaptureExtension.class})
class ReferenceDataServiceTests {
    @Mock ReferenceDataRepository repository;
    @Mock AuthService auth;
    @InjectMocks ReferenceDataService service;

    @BeforeEach
    void authenticatedMember() {
        when(auth.currentUser(1)).thenReturn(new LoginUser(1, "검사용", "검사 기관", null,
                "11", "11680", false, "reference@example.test", 7));
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = " ")
    void missingSidoNameFailsAndIdentifiesMappingCode(String name, CapturedOutput output) {
        when(repository.sidos()).thenReturn(List.of(new ReferenceDataDtos.SidoItem("99", name)));
        assertThatThrownBy(() -> service.sidos(1)).isInstanceOfSatisfying(ApiException.class,
                ex -> assertThat(ex.code()).isEqualTo(ErrorCode.INTERNAL_SERVER_ERROR));
        assertThat(output.getOut()).contains("Missing sido name mapping", "sidoCode=99");
    }

    @Test
    void unpopulatedRegionDataReturnsEmptyList() {
        when(repository.sidos()).thenReturn(List.of());
        assertThat(service.sidos(1)).isEmpty();
    }
}
