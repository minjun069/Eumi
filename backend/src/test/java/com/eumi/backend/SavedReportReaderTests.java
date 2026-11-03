package com.eumi.backend;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import com.eumi.backend.analysis.SavedReportReader;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import static org.assertj.core.api.Assertions.*;

class SavedReportReaderTests {
    private final JsonMapper json = JsonMapper.builder().build();
    private final SavedReportReader reader = new SavedReportReader(json);
    private static final Instant GENERATED = Instant.parse("2026-11-03T00:00:00Z");

    private String fixture() throws Exception {
        try (var stream = getClass().getResourceAsStream("/analysis/report.json")) {
            return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    @Test
    void allBlockAndChartVariantsPreserveTheirContractAndDatabaseTimestamp() throws Exception {
        var body = (ObjectNode) json.readTree(fixture());
        body.put("generatedAt", "2000-01-01T00:00:00Z");
        var result = json.valueToTree(reader.read(body.toString(), GENERATED));
        assertThat(result.path("headline").asText()).isEqualTo("Synthetic **analysis** report");
        assertThat(result.path("sections")).isEqualTo(body.path("sections"));
        assertThat(result.path("sections").get(0).has("question")).isTrue();
        assertThat(result.path("sections").get(0).path("question").isNull()).isTrue();
        assertThat(Instant.parse(result.path("generatedAt").asText())).isEqualTo(GENERATED);
        assertThat(result.size()).isEqualTo(3);
    }

    @ParameterizedTest
    @ValueSource(strings = {"not-json", "null", "[]", "{}", "{\"headline\":null,\"sections\":[]}",
            "{\"headline\":\"x\",\"sections\":[{\"blocks\":[]}]}",
            "{\"headline\":\"x\",\"sections\":[],\"unknown\":true}"})
    void malformedContentFailsWithoutEchoingStoredText(String content) {
        assertThatThrownBy(() -> reader.read(content, GENERATED)).isInstanceOf(IllegalArgumentException.class)
                .hasMessage("Invalid saved report");
    }

    @Test
    void invalidGraphRelationshipsAndUnknownFieldsAreRejected() throws Exception {
        String valid = fixture();
        for (String invalid : new String[]{
                valid.replace("\"rank\":4", "\"rank\":23"),
                valid.replace("\"q1\":5", "\"q1\":20"),
                valid.replace("\"changes\":[20,-10]", "\"changes\":[20]"),
                valid.replace("\"count\":3", "\"count\":23"),
                valid.replace("\"value\":3", "\"value\":-3"),
                valid.replace("\"type\":\"ratio\"", "\"type\":\"unknown\""),
                valid.replace("\"kind\":\"paragraph\"", "\"kind\":\"unknown\""),
                valid.replace("\"stage\":2", "\"stage\":0"),
                valid.replace("\"month\":\"2025-11\"", "\"month\":\"2025-12\"")}) {
            assertThatThrownBy(() -> reader.read(invalid, GENERATED)).isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Test
    void absentGenerationTimestampIsNotFabricated() throws Exception {
        assertThatThrownBy(() -> reader.read(fixture(), null)).isInstanceOf(IllegalArgumentException.class);
    }
}
