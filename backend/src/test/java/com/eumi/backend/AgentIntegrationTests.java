package com.eumi.backend;

import java.time.Instant;
import java.time.ZoneId;
import java.util.UUID;
import java.util.stream.Stream;
import com.eumi.backend.agent.AiConversation;
import com.eumi.backend.agent.AiMessage;
import com.eumi.backend.agent.AgentMessageWriter;
import com.eumi.backend.support.AgentHttpSupport;
import jakarta.persistence.EntityManager;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataIntegrityViolationException;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = "eumi.ai.fake-step-delay=300ms")
class AgentIntegrationTests extends AgentHttpSupport {
    @Autowired AgentMessageWriter writer;
    @Autowired EntityManager entities;

    @ParameterizedTest
    @MethodSource("storedMaskingCases")
    void masksPrivateValuesAndPreservesQuestionsInActualStorageAndHttp(String input, String expected) throws Exception {
        var accepted = browser.post("/agent/questions", question(null, input));
        assertThat(accepted.statusCode()).isEqualTo(202);
        var created = body(accepted);
        UUID id = conversation(created);
        long questionId = created.path("data").path("questionId").asLong();
        assertThat(jdbc.queryForObject("SELECT content FROM ai_message WHERE message_id = ?", String.class, questionId))
                .isEqualTo(expected);
        assertThat(awaitEnd(id).path("status").asText()).isEqualTo("완료");
        var response = browser.get(messagesPath(id) + "?after=0");
        assertThat(response.statusCode()).isEqualTo(200);
        var question = body(response).path("data").path("messages").get(0);
        assertThat(question.path("messageId").asLong()).isEqualTo(questionId);
        assertThat(question.path("role").asText()).isEqualTo("Member");
        assertThat(question.path("content").asText()).isEqualTo(expected);
    }

    static Stream<Arguments> storedMaskingCases() {
        return Stream.of(
                Arguments.of("사례자명: 박 지원; 위험도는?\n생년월일: 1950-01-02; 연령대 분석\n"
                                + "010-1234-5678, person@example.test",
                        "사례자명: [이름]; 위험도는?\n생년월일: [생년월일]; 연령대 분석\n[전화번호], [이메일]"),
                Arguments.of("주민번호: 900101-1234567; 계좌번호: 123.456/789; 카드번호: 1234-5678-9012-3456\n"
                                + "주소: 서울 어느로 12; 행정동 1168010100; 관리번호 2026-0001; 분석기간 2026-11-03",
                        "주민번호: 900101-1234567; 계좌번호: 123.456/789; 카드번호: 1234-5678-9012-3456\n"
                                + "주소: 서울 어느로 12; 행정동 1168010100; 관리번호 2026-0001; 분석기간 2026-11-03"));
    }

    @Test
    void questionProgressCompletionAfterCursorAndFollowupUseActualDbAndHttp() throws Exception {
        var accepted = browser.post("/agent/questions", question(null, "강남구 위험도; 이름: 홍길동; 010-1234-5678, person@example.test"));
        assertThat(accepted.statusCode()).isEqualTo(202);
        assertThat(accepted.headers().firstValue("Cache-Control").orElseThrow()).isEqualTo("no-store");
        var created = body(accepted);
        UUID id = conversation(created);
        long questionId = created.path("data").path("questionId").asLong();
        String stored = jdbc.queryForObject("SELECT content FROM ai_message WHERE message_id = ?", String.class, questionId);
        assertThat(stored).contains("[이름]", "[전화번호]", "[이메일]").doesNotContain("홍길동", "010-1234-5678", "person@example.test");

        var terminal = awaitEnd(id);
        assertThat(terminal.path("status").asText()).isEqualTo("완료");
        var full = body(browser.get(messagesPath(id))).path("data").path("messages");
        assertThat(full.get(0).path("role").asText()).isEqualTo("Member");
        assertThat(full.get(0).path("questionId").isNull()).isTrue();
        var rows = body(browser.get(messagesPath(id) + "?after=" + questionId)).path("data").path("messages");
        assertThat(rows.size()).isEqualTo(4);
        long cursor = questionId;
        for (var row : rows) {
            assertThat(row.size()).isEqualTo(8);
            assertThat(row.path("messageId").asLong()).isGreaterThan(cursor);
            cursor = row.path("messageId").asLong();
            assertThat(row.path("questionId").asLong()).isEqualTo(questionId);
            assertThat(row.path("role").asText()).isEqualTo("AI");
            assertThat(row.has("details") && row.has("artifacts")).isTrue();
            Instant.parse(row.path("createdAt").asText());
        }
        assertThat(body(browser.get(messagesPath(id) + "?after=" + cursor)).path("data").path("messages").isEmpty()).isTrue();
        var mapped = entities.find(AiConversation.class, id);
        assertThat(mapped.getLastMessageAt()).isEqualTo(Instant.parse(terminal.path("createdAt").asText()));
        assertThat(mapped.getDeleteScheduledAt()).isEqualTo(mapped.getLastMessageAt().atZone(ZoneId.of("Asia/Seoul")).toLocalDate().plusMonths(3));
        assertThat(entities.find(AiMessage.class, questionId).getContent()).isEqualTo(stored);

        assertThatThrownBy(() -> jdbc.update("INSERT INTO ai_message(conversation_id, question_id, role, status, content) "
                + "VALUES (?, ?, 'AI', '진행', '늦은 단계')", id, questionId)).isInstanceOf(DataIntegrityViolationException.class)
                .satisfies(ex -> assertThat(((java.sql.SQLException) ((DataIntegrityViolationException) ex).getMostSpecificCause()).getSQLState())
                        .isEqualTo("23505"));
        assertThat(writer.append(id, questionId, "진행", "늦은 단계", null)).isFalse();
        assertThat(writer.append(id, questionId, "취소", null, null)).isFalse();
        var followup = browser.post("/agent/questions", question(id, "주변 동과 비교해 줘"));
        assertThat(followup.statusCode()).isEqualTo(202);
        assertThat(conversation(body(followup))).isEqualTo(id);
        assertThat(body(followup).path("data").path("questionId").asLong()).isGreaterThan(cursor);
    }

    @Test
    void fakeCancellationWritesOneTerminalAndRepeatedCancelIsNoOp() throws Exception {
        UUID id = conversation(body(browser.post("/agent/questions", question(null, "중단 검사"))));
        assertThat(browser.post(cancelPath(id), null).statusCode()).isEqualTo(204);
        assertThat(awaitEnd(id).path("status").asText()).isEqualTo("취소");
        assertThat(browser.post(cancelPath(id), null).statusCode()).isEqualTo(204);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM ai_message WHERE conversation_id = ? "
                + "AND status IN ('완료','실패','취소')", Integer.class, id)).isEqualTo(1);
    }

    @Test
    void otherMembersAndExpiredConversationsAre404OnEveryOperation() throws Exception {
        UUID id = conversation(body(browser.post("/agent/questions", question(null, "소유권 검사"))));
        var other = signIn(otherEmail);
        assertThat(other.get(messagesPath(id)).statusCode()).isEqualTo(404);
        assertThat(other.post(cancelPath(id), null).statusCode()).isEqualTo(404);
        assertThat(other.post("/agent/questions", question(id, "다른 회원 질문")).statusCode()).isEqualTo(404);
        jdbc.update("UPDATE ai_conversation SET delete_scheduled_at = current_date WHERE conversation_id = ?", id);
        assertThat(browser.get(messagesPath(id)).statusCode()).isEqualTo(404);
        assertThat(browser.post(cancelPath(id), null).statusCode()).isEqualTo(404);
        assertThat(browser.post("/agent/questions", question(id, "만료 대화 질문")).statusCode()).isEqualTo(404);
    }

    @Test
    void restrictedSessionCannotUseAnyAgentOperation() throws Exception {
        jdbc.update("UPDATE member SET temp_password_expires_at = now() + interval '1 hour' WHERE member_id = ?", memberId);
        browser = signIn(email);
        var result = browser.post("/agent/questions", question(null, "제한 세션 검사"));
        assertThat(result.statusCode()).isEqualTo(403);
        assertThat(body(result).path("error").path("code").asText()).isEqualTo("PASSWORD_CHANGE_REQUIRED");
        assertThat(browser.get(messagesPath(UUID.randomUUID())).statusCode()).isEqualTo(403);
        assertThat(browser.post(cancelPath(UUID.randomUUID()), null).statusCode()).isEqualTo(403);
    }

    @Test
    void validatesRequiredFieldsUnknownScreenCodePointLengthAndCursor() throws Exception {
        assertThat(browser.post("/agent/questions", "{\"question\":\"질문\"}").statusCode()).isEqualTo(400);
        assertThat(browser.post("/agent/questions", "{\"conversationId\":null,\"question\":\"질문\",\"screen\":\"dashboard\"}").statusCode()).isEqualTo(400);
        assertThat(browser.post("/agent/questions", question(null, "   ")).statusCode()).isEqualTo(400);
        assertThat(browser.post("/agent/questions", question(null, "가".repeat(4001))).statusCode()).isEqualTo(400);
        var accepted = browser.post("/agent/questions", question(null, "\uD83D\uDE00".repeat(4000)));
        assertThat(accepted.statusCode()).isEqualTo(202);
        UUID id = conversation(body(accepted));
        assertThat(browser.get(messagesPath(id) + "?after=-1").statusCode()).isEqualTo(400);
        assertThat(browser.get(messagesPath(id) + "?after=9007199254740992").statusCode()).isEqualTo(400);
        assertThat(new Browser().get(messagesPath(id)).statusCode()).isEqualTo(401);
    }
}
