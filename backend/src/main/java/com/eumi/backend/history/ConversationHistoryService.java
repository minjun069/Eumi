package com.eumi.backend.history;

import java.util.UUID;
import com.eumi.backend.agent.*;
import com.eumi.backend.auth.login.AuthService;
import com.eumi.backend.common.error.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.*;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class ConversationHistoryService {
    private final ConversationHistoryRepository repository;
    private final AgentRepository messages;
    private final AgentLifecycle lifecycle;
    private final AuthService auth;
    private final TransactionTemplate transaction;
    public ConversationHistoryService(ConversationHistoryRepository repository,AgentRepository messages,
            AgentLifecycle lifecycle,AuthService auth,PlatformTransactionManager manager) {
        this.repository=repository;this.messages=messages;this.lifecycle=lifecycle;this.auth=auth;
        transaction=new TransactionTemplate(manager);
    }
    private void requireMember(long member) {
        if(auth.currentUser(member).mustChangePassword())throw new ApiException(ErrorCode.PASSWORD_CHANGE_REQUIRED);
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public ConversationHistoryDtos.Page list(long member,ConversationHistoryDtos.Search search) {
        requireMember(member);return repository.list(member,search);
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public ConversationHistoryDtos.Detail detail(long member,UUID id) {
        requireMember(member);var info=repository.info(member,id);
        // 기록 조회는 기존 메시지 매핑만 재사용한다. AI 복구·재실행을 요청하지 않는다.
        var rows=messages.messages(id,0);
        return new ConversationHistoryDtos.Detail(id,info.firstQuestion(),info.lastMessageAt(),info.deleteScheduledAt(),rows);
    }
    public void delete(long member,UUID id) {
        requireMember(member);messages.requireOwned(id,member,false);
        // Fake 취소도 독립 트랜잭션으로 끝 행을 쓴다. 대화 잠금을 잡기 전에 취소를 요청한다.
        lifecycle.cancel(id);
        transaction.executeWithoutResult(tx->{
            requireMember(member);messages.requireOwned(id,member,true);repository.delete(member,id);
        });
    }
}
