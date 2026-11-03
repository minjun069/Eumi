package com.eumi.backend.agent;

import java.util.UUID;
import com.eumi.backend.auth.login.AuthService;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class AgentService {
    private final AgentRepository repository;
    private final AgentLifecycle lifecycle;
    private final AuthService auth;
    private final QuestionMasker masker;
    private final TransactionTemplate transaction;

    public AgentService(AgentRepository repository, AgentLifecycle lifecycle, AuthService auth,
            QuestionMasker masker, PlatformTransactionManager manager) {
        this.repository = repository; this.lifecycle = lifecycle; this.auth = auth; this.masker = masker;
        transaction = new TransactionTemplate(manager);
    }

    private void requireMember(long memberId) {
        if (auth.currentUser(memberId).mustChangePassword()) throw new ApiException(ErrorCode.PASSWORD_CHANGE_REQUIRED);
    }

    public AgentDtos.QuestionCreated ask(long memberId, AgentDtos.QuestionRequest input) {
        requireMember(memberId);
        var created = transaction.execute(tx -> {
            UUID id = input.conversationId();
            if (id == null) {
                id = UUID.randomUUID();
                repository.createConversation(id, memberId);
            } else {
                repository.requireOwned(id, memberId, true);
                if (repository.activeQuestion(id).isPresent()) throw new ApiException(ErrorCode.RUN_ALREADY_ACTIVE);
            }
            return new AgentDtos.QuestionCreated(id, repository.insertQuestion(id, masker.mask(input.question())));
        });
        // AI는 반드시 질문 저장 커밋이 끝난 다음 호출한다.
        lifecycle.start(created.conversationId(), created.questionId());
        return created;
    }

    public AgentDtos.Messages messages(long memberId, UUID id, long after) {
        requireMember(memberId);
        repository.requireOwned(id, memberId, false);
        try { lifecycle.recover(id); }
        catch (RuntimeException ex) {
            // 복구 쓰기와 읽기를 분리한다. 권한 검사와 실제 메시지 조회의 오류는 그대로 처리한다.
            AgentDiagnostics.failure(id, "recover", ex);
        }
        return new AgentDtos.Messages(repository.messages(id, after));
    }

    public void cancel(long memberId, UUID id) {
        requireMember(memberId);
        repository.requireOwned(id, memberId, false);
        lifecycle.cancel(id);
    }
}
