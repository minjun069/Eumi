package com.eumi.backend;

import java.util.UUID;
import com.eumi.backend.internal.InternalApiProperties;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class InternalApiPropertiesTests {
    @Test void fakeCanStartWithoutTokensButNothingCanAuthenticate() {
        var properties = new InternalApiProperties(); properties.afterPropertiesSet();
        assertThat(properties.caller("")).isNull();
        assertThat(properties.caller(UUID.randomUUID().toString())).isNull();
        assertThatThrownBy(properties::requireHttpTokens).hasMessage("HTTP AI mode requires both internal service tokens.");
    }
    @Test void twoIndependentTokensAreRequiredForHttpAndNeverPrinted() {
        var properties = new InternalApiProperties();
        String ai = UUID.randomUUID().toString(), pipeline = UUID.randomUUID().toString();
        properties.setAiToken(ai); properties.setPipelineToken(pipeline); properties.afterPropertiesSet(); properties.requireHttpTokens();
        assertThat(properties.caller(ai)).isEqualTo("AI"); assertThat(properties.caller(pipeline)).isEqualTo("PIPELINE");
        assertThat(properties.toString()).isEqualTo("InternalApiProperties[redacted]");
        properties.setPipelineToken(ai);
        assertThatThrownBy(properties::afterPropertiesSet).hasMessage("Internal service tokens must be distinct.");
    }
}
