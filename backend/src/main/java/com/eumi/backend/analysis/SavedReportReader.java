package com.eumi.backend.analysis;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Set;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** 저장된 보고서를 계약 범위에서 읽는다. 생성·정규화·누락 값 보충은 수행하지 않는다. */
@Component
public class SavedReportReader {
    private static final long SAFE_INTEGER = 9007199254740991L;
    private final JsonMapper json;

    public SavedReportReader(JsonMapper json) { this.json = json; }

    public AnalysisDtos.Report read(String content, Instant generatedAt) {
        check(content != null && generatedAt != null);
        JsonNode body;
        try { body = json.readTree(content); }
        catch (RuntimeException ex) { throw invalid(); }
        check(body.isObject() && body.has("headline") && body.has("sections")
                && Set.of("headline", "sections", "generatedAt").containsAll(body.propertyNames()));
        text(body.path("headline"));
        var sections = body.path("sections");
        array(sections, 0);
        for (var section : sections) {
            exact(section, "question", "blocks");
            check(section.path("question").isNull() || section.path("question").isString());
            array(section.path("blocks"), 0);
            for (var block : section.path("blocks")) block(block);
        }
        // JSON 안의 generatedAt보다 DB generated_at을 응답 시각의 기준으로 사용한다.
        return new AnalysisDtos.Report(body.path("headline").asText(), sections, generatedAt);
    }

    private void block(JsonNode block) {
        text(block.path("kind"));
        switch (block.path("kind").asText()) {
            case "paragraph" -> { exact(block, "kind", "text"); text(block.path("text")); }
            case "bullets" -> {
                exact(block, "kind", "items"); array(block.path("items"), 0);
                for (var item : block.path("items")) { exact(item, "label", "text"); text(item.path("label")); text(item.path("text")); }
            }
            case "chart" -> { exact(block, "kind", "chart"); chart(block.path("chart")); }
            default -> throw invalid();
        }
    }

    private void chart(JsonNode chart) {
        text(chart.path("type"));
        switch (chart.path("type").asText()) {
            case "trend" -> {
                exact(chart, "type", "heading", "total", "points"); text(chart.path("heading"));
                long total = integer(chart.path("total"), 1, SAFE_INTEGER);
                array(chart.path("points"), 1);
                String previous = "";
                for (var point : chart.path("points")) {
                    exact(point, "month", "score", "stage", "rank", "median", "q1", "q3");
                    text(point.path("month")); String month = point.path("month").asText();
                    check(month.matches("[0-9]{4}-(0[1-9]|1[0-2])") && month.compareTo(previous) > 0);
                    previous = month;
                    number(point.path("score")); integer(point.path("stage"), 1, 5); integer(point.path("rank"), 1, total);
                    var median = number(point.path("median"));
                    check(number(point.path("q1")).compareTo(median) <= 0 && median.compareTo(number(point.path("q3"))) <= 0);
                }
            }
            case "factors", "compare" -> {
                exact(chart, "type", "heading", "items"); text(chart.path("heading")); array(chart.path("items"), 1);
                boolean compare = chart.path("type").asText().equals("compare");
                for (var item : chart.path("items")) {
                    if (compare) { exact(item, "label", "value", "highlight"); check(item.path("highlight").isBoolean()); }
                    else exact(item, "label", "value");
                    text(item.path("label")); var value = number(item.path("value"));
                    if (compare) check(value.signum() >= 0);
                }
            }
            case "weekday" -> {
                exact(chart, "type", "heading", "caption", "unit", "days", "series", "changes");
                text(chart.path("heading")); text(chart.path("caption")); text(chart.path("unit"));
                array(chart.path("days"), 1); chart.path("days").forEach(this::text);
                int days = chart.path("days").size();
                array(chart.path("series"), 2); check(chart.path("series").size() == 2);
                for (var series : chart.path("series")) {
                    exact(series, "label", "values"); text(series.path("label")); array(series.path("values"), days);
                    check(series.path("values").size() == days);
                    for (var value : series.path("values")) check(number(value).signum() >= 0);
                }
                array(chart.path("changes"), days); check(chart.path("changes").size() == days);
                chart.path("changes").forEach(this::number);
            }
            case "ratio" -> {
                exact(chart, "type", "count", "total", "caption"); text(chart.path("caption"));
                long total = integer(chart.path("total"), 1, SAFE_INTEGER); integer(chart.path("count"), 0, total);
            }
            default -> throw invalid();
        }
    }

    private void exact(JsonNode node, String... fields) {
        check(node.isObject() && node.size() == fields.length);
        for (String field : fields) check(node.has(field));
    }
    private void array(JsonNode node, int minimum) { check(node.isArray() && node.size() >= minimum); }
    private void text(JsonNode node) { check(node.isString()); }
    private BigDecimal number(JsonNode node) {
        check(node.isNumber() && Double.isFinite(node.doubleValue()));
        return node.decimalValue();
    }
    private long integer(JsonNode node, long minimum, long maximum) {
        check(node.isIntegralNumber()); var value = number(node);
        check(value.compareTo(BigDecimal.valueOf(minimum)) >= 0 && value.compareTo(BigDecimal.valueOf(maximum)) <= 0);
        return value.longValueExact();
    }
    private void check(boolean valid) { if (!valid) throw invalid(); }
    private IllegalArgumentException invalid() { return new IllegalArgumentException("Invalid saved report"); }
}
