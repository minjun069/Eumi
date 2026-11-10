package com.eumi.backend.mypage;

import java.util.*;
import java.util.stream.Collectors;
import com.eumi.backend.agent.AgentLifecycle;
import com.eumi.backend.auth.login.*;
import com.eumi.backend.auth.password.PasswordChangeRepository;
import com.eumi.backend.common.error.*;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.*;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class WithdrawalService {
    private final WithdrawalRepository repository;
    private final PasswordChangeRepository accounts;
    private final PasswordEncoder passwords;
    private final AuthService auth;
    private final AgentLifecycle lifecycle;
    private final TransactionTemplate transaction;
    public WithdrawalService(WithdrawalRepository repository, PasswordChangeRepository accounts,
            PasswordEncoder passwords, AuthService auth, AgentLifecycle lifecycle, PlatformTransactionManager manager) {
        this.repository=repository; this.accounts=accounts; this.passwords=passwords;
        this.auth=auth; this.lifecycle=lifecycle; transaction=new TransactionTemplate(manager);
    }
    private LoginUser requireUser(long member) {
        var user=auth.currentUser(member);
        if (user.mustChangePassword()) throw new ApiException(ErrorCode.PASSWORD_CHANGE_REQUIRED);
        return user;
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public WithdrawalDtos.Info info(long member) {
        var user=requireUser(member);
        var ongoing=repository.ongoingResources(member);
        long ended=repository.endedResourceCount(member);
        return new WithdrawalDtos.Info(repository.soleCases(member),repository.sharedCaseCount(member),
                repository.successors(user.orgId(),member),ongoing.size()+ended,repository.conversationCount(member),ongoing,ended);
    }
    public void withdraw(long member, WithdrawalDtos.Request input) {
        input.validateFor(member);
        requireUser(member);
        var before=accounts.account(member,false).filter(a->!a.withdrawn()).orElseThrow(()->new ApiException(ErrorCode.NOT_FOUND));
        boolean matches;
        try { matches=passwords.matches(input.password(),before.hash()); }
        catch (IllegalArgumentException ex) { matches=false; }
        if (!matches) throw new ApiException(ErrorCode.WITHDRAW_PASSWORD_MISMATCH);

        // fake 취소도 별도 트랜잭션으로 끝 행을 쓴다. 업무 잠금을 얻기 전에 요청한다.
        for (var id : repository.activeConversations(member)) lifecycle.cancel(id);
        var memberIds=new TreeSet<Long>(); memberIds.add(member);
        input.transfers().forEach(t->memberIds.add(t.newManagerMemberId()));
        input.resourceTransfers().forEach(t->memberIds.add(t.newManagerMemberId()));
        transaction.executeWithoutResult(tx->{
            repository.lockOrganization(before.orgId());
            var locked=repository.lockMembers(memberIds).stream().collect(Collectors.toMap(WithdrawalRepository.LockedMember::memberId,
                    WithdrawalRepository.LockedMember::account));
            var current=locked.get(member);
            if (current==null || current.withdrawn()) throw new ApiException(ErrorCode.NOT_FOUND);
            if (!Objects.equals(current.hash(),before.hash())) throw new ApiException(ErrorCode.WITHDRAW_PASSWORD_MISMATCH);
            requireUser(member);
            if (current.orgId()!=before.orgId() || memberIds.stream().anyMatch(id->!locked.containsKey(id)
                    || locked.get(id).withdrawn() || locked.get(id).orgId()!=before.orgId())) throw conflict();
            repository.lockCases(member);
            repository.lockResources(member);
            var cases=input.transfers().stream().map(WithdrawalDtos.Transfer::caseId).collect(Collectors.toSet());
            var resources=input.resourceTransfers().stream().map(WithdrawalDtos.ResourceTransfer::resourceId).collect(Collectors.toSet());
            var ongoing=repository.ongoingResources(member).stream().map(WithdrawalDtos.OngoingResource::resourceId).collect(Collectors.toSet());
            if (!cases.equals(repository.soleCaseIds(member)) || !resources.equals(ongoing)) throw conflict();

            input.transfers().forEach(repository::transferCase);
            repository.deleteCaseLinks(member);
            for (var transfer : input.resourceTransfers()) if (repository.transferResource(member,transfer)!=1) throw conflict();
            repository.deleteConversations(member);
            if (repository.withdrawMember(member)!=1) throw conflict();
            accounts.deleteAllSessions(member);
        });
    }
    private static ApiException conflict() { return new ApiException(ErrorCode.STATE_CONFLICT); }
}
