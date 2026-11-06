package com.eumi.backend;

import java.time.*;
import java.util.List;
import com.eumi.backend.cases.*;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import jakarta.validation.Validation;
import jakarta.validation.ValidatorFactory;
import org.junit.jupiter.api.*;
import static org.assertj.core.api.Assertions.*;

class CaseValidationTests {
    private static ValidatorFactory factory;
    @BeforeAll static void setup(){factory=Validation.buildDefaultValidatorFactory();}
    @AfterAll static void close(){factory.close();}

    private CaseDtos.Input input(String name,List<Long> managers) {
        return new CaseDtos.Input(name,LocalDate.of(1980,1,1),"남","1168066000",LocalDate.of(2020,1,1),managers);
    }
    @Test
    void nameLimitCountsUnicodeCodePointsAndTrimsInput() {
        assertThat(factory.getValidator().validate(input("  "+"😀".repeat(100)+"  ",List.of(1L)))).isEmpty();
        assertThat(factory.getValidator().validate(input("😀".repeat(101),List.of(1L)))).isNotEmpty();
        assertThat(factory.getValidator().validate(input("  ",List.of(1L)))).isNotEmpty();
    }
    @Test
    void managersMustHaveAtLeastOneValidSafeInteger() {
        for(var managers:List.of(List.<Long>of(),List.of(0L),List.of(CaseDtos.MAX_ID+1)))
            assertThat(factory.getValidator().validate(input("Synthetic",managers))).isNotEmpty();
    }
    @Test
    void consultationLimitsUseCodePointsAndUnrelatedEtcIsNormalizedAway() {
        var valid=new ConsultationDtos.Input(LocalDate.of(2020,1,1),"😀".repeat(200),"기타","😀".repeat(20),"😀".repeat(20000));
        assertThat(factory.getValidator().validate(valid)).isEmpty();
        var tooLong=new ConsultationDtos.Input(valid.consultedAt(),valid.purpose()+"x",valid.category(),valid.categoryEtc()+"x",valid.content()+"x");
        assertThat(factory.getValidator().validate(tooLong)).hasSize(3);
        assertThat(new ConsultationDtos.Input(valid.consultedAt(),"Synthetic purpose","정기상담","discarded","Synthetic content").categoryEtc()).isNull();
    }
    @Test
    void futureDateRuleUsesKoreanDateEvenWhenUtcDateDiffers() {
        var service=new CaseService(null,null,Clock.fixed(Instant.parse("2026-11-04T16:00:00Z"),ZoneOffset.UTC));
        assertThatCode(()->service.validateDate(LocalDate.of(2026,11,5))).doesNotThrowAnyException();
        assertThatThrownBy(()->service.validateDate(LocalDate.of(2026,11,6))).isInstanceOfSatisfying(ApiException.class,
                e->assertThat(e.code()).isEqualTo(ErrorCode.VALIDATION_ERROR));
    }
    @Test
    void requestToStringsRedactPrivateInput() {
        assertThat(input("Synthetic private name",List.of(1L)).toString()).doesNotContain("Synthetic private name");
        assertThat(new CaseDtos.DuplicateInput("Synthetic private name",LocalDate.of(1980,1,1),null).toString()).doesNotContain("Synthetic private name");
        assertThat(new ConsultationDtos.Input(LocalDate.of(2020,1,1),"Synthetic purpose","기타","Synthetic other","Synthetic content").toString())
                .doesNotContain("Synthetic purpose","Synthetic content");
    }
}
