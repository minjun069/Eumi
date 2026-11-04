package com.eumi.backend;

import java.time.LocalDate;
import java.util.*;
import com.eumi.backend.resources.ResourceDtos;
import jakarta.validation.Validation;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.assertj.core.api.Assertions.*;

class ResourceValidationTests {
    @ParameterizedTest
    @ValueSource(ints={50,51})
    void stringLimitsCountUnicodeCodePointsInsteadOfUtf16Units(int length) {
        try(var factory=Validation.buildDefaultValidatorFactory()) {
            var input=input("😀".repeat(length),List.of("무관")," ");
            var fields=factory.getValidator().validate(input).stream().map(v->v.getPropertyPath().toString()).toList();
            assertThat(fields.contains("resourceName")).isEqualTo(length>50);
        }
    }
    @Test
    void inputTrimsDeduplicatesAndKeepsContentOutOfToString() {
        var i=input(" Synthetic resource ",List.of(" 청년 ","노년","청년"),"  ");
        assertThat(i.resourceName()).isEqualTo("Synthetic resource");assertThat(i.supportAgeGroups()).containsExactly("청년","노년");
        assertThat(i.supportContent()).isNull();assertThat(i.applyMethod()).isNull();assertThat(i.toString()).doesNotContain("Synthetic resource");
    }
    private ResourceDtos.Input input(String name,List<String> ages,String content) {
        return new ResourceDtos.Input(name,"Synthetic org","Synthetic target",ages,"무관","11680",null,
                LocalDate.of(2030,1,1),LocalDate.of(2030,1,2),0L,"진행 중",1L,1L,null,content,null);
    }
}
