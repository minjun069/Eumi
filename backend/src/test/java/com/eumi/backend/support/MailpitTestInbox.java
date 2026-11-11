package com.eumi.backend.support;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** 검사가 만든 고유 수신자만 조회·삭제한다. 메일 본문은 출력하지 않는다. */
public final class MailpitTestInbox {
    private final HttpClient http = HttpClient.newHttpClient();
    private final JsonMapper json;
    public MailpitTestInbox(JsonMapper json) { this.json = json; }

    public List<String> ids(Set<String> recipients) throws Exception {
        List<String> result = new ArrayList<>();
        for (int start = 0; ; start += 100) {
            var response = http.send(request("/messages?limit=100&start=" + start).GET().build(), HttpResponse.BodyHandlers.ofString());
            require(response.statusCode() == 200, "Mailpit message listing failed");
            var messages = json.readTree(response.body()).path("messages");
            for (var message : messages) {
                boolean owned = false;
                for (var address : message.path("To")) if (recipients.contains(address.path("Address").asText())) owned = true;
                if (owned) {
                    String id = message.path("ID").asText();
                    require(!id.isBlank(), "Mailpit message ID missing"); result.add(id);
                }
            }
            if (messages.size() < 100) return result;
        }
    }
    public JsonNode message(String id) throws Exception {
        var response = http.send(request("/message/" + id).GET().build(), HttpResponse.BodyHandlers.ofString());
        require(response.statusCode() == 200, "Mailpit message read failed");
        return json.readTree(response.body());
    }
    public void deleteOwned(Set<String> recipients) throws Exception {
        var ids = ids(recipients);
        // Mailpit는 빈 ID 목록이면 전체 삭제다. 빈 목록은 절대 보내지 않는다.
        if (ids.isEmpty()) return;
        var response = http.send(request("/messages").header("Content-Type", "application/json")
                .method("DELETE", HttpRequest.BodyPublishers.ofString(json.writeValueAsString(Map.of("IDs", ids)))).build(),
                HttpResponse.BodyHandlers.discarding());
        require(response.statusCode() == 200, "Owned Mailpit message deletion failed");
    }
    private HttpRequest.Builder request(String path) {
        return HttpRequest.newBuilder(URI.create("http://localhost:8025/api/v1" + path)).timeout(Duration.ofSeconds(5));
    }
    private void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
