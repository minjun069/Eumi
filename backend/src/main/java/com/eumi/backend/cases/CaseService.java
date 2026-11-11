package com.eumi.backend.cases;

import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;
import com.eumi.backend.auth.login.AuthService;
import com.eumi.backend.auth.login.LoginUser;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional(readOnly = true)
public class CaseService {
    private final CaseRepository repository;
    private final AuthService auth;
    private final Clock clock;

    public CaseService(CaseRepository repository, AuthService auth, Clock clock) {
        this.repository = repository; this.auth = auth; this.clock = clock;
    }

    public LoginUser requireUser(long id) {
        var user = auth.currentUser(id);
        if (user.mustChangePassword()) throw new ApiException(ErrorCode.PASSWORD_CHANGE_REQUIRED);
        return user;
    }

    public CaseRepository.Access requireAccess(LoginUser user, long caseId, boolean lock) {
        var access = repository.access(caseId, user.orgId(), user.memberId(), lock).orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND));
        if (access.orgId() != user.orgId()) throw new ApiException(ErrorCode.NOT_FOUND);
        if (!access.assigned()) throw new ApiException(ErrorCode.FORBIDDEN);
        return access;
    }

    public CaseDtos.Page search(long member, CaseDtos.Search search) {
        var user = requireUser(member);
        validateSearch(search);
        return repository.search(user.orgId(), user.memberId(), search);
    }
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public CaseDtos.Detail detail(long member, long caseId) {
        var user = requireUser(member); requireAccess(user, caseId, false); return repository.detail(caseId);
    }
    public CaseDtos.Duplicates duplicates(long member, CaseDtos.DuplicateInput input) {
        var user = requireUser(member); validateDate(input.birthDate());
        return new CaseDtos.Duplicates(repository.duplicates(user.orgId(), member, input));
    }

    @Transactional
    public CaseDtos.Created create(long member, CaseDtos.Input input) {
        validateDatesAndRegion(input);
        var managers = new TreeSet<>(input.managerMemberIds()); managers.add(member);
        var user = lockWriter(member, managers, ErrorCode.VALIDATION_ERROR);
        String year = String.format(Locale.ROOT, "%04d", input.firstRegisteredAt().getYear());
        if (repository.lastNumber(user.orgId(), year) >= 9999) throw new ApiException(ErrorCode.MANAGEMENT_NUMBER_EXHAUSTED);
        // 조직 잠금·한도 검사·함수 호출·사례자/담당자 INSERT가 같은 트랜잭션이다.
        String number = repository.nextNumber(user.orgId(), input.firstRegisteredAt());
        long id = repository.insert(user.orgId(), number, input);
        repository.replaceManagers(id, managers);
        return new CaseDtos.Created(id, number);
    }

    @Transactional
    public void update(long member, long caseId, CaseDtos.UpdateInput request) {
        requireAccess(requireUser(member), caseId, false);
        var input = request.input();
        validateDatesAndRegion(input);
        var expected = request.expectedUpdatedAt().truncatedTo(ChronoUnit.MICROS);
        var managers = new TreeSet<>(input.managerMemberIds());
        var lockIds = new TreeSet<>(managers); lockIds.add(member);
        var user = lockWriter(member, lockIds, ErrorCode.VALIDATION_ERROR);
        var current = requireAccess(user, caseId, true);
        if (!current.updatedAt().truncatedTo(ChronoUnit.MICROS).equals(expected)) throw new ApiException(ErrorCode.STATE_CONFLICT);
        repository.update(caseId, input);
        repository.replaceManagers(caseId, managers);
    }

    @Transactional
    public void delete(long member, long caseId) {
        var user = lockWriter(member, List.of(member), ErrorCode.FORBIDDEN);
        requireAccess(user, caseId, true); repository.delete(caseId);
    }

    public LoginUser lockWriter(long member, Collection<Long> memberIds, ErrorCode invalidManager) {
        var before = requireUser(member);
        repository.lockOrganization(before.orgId());
        var active = repository.lockActiveMembers(before.orgId(), memberIds);
        var current = requireUser(member);
        if (current.orgId() != before.orgId()) throw new ApiException(ErrorCode.FORBIDDEN);
        if (!active.containsAll(memberIds)) throw new ApiException(invalidManager);
        return current;
    }

    public void validateDate(LocalDate date) {
        if (date == null || date.getYear() < 1 || date.getYear() > 9999 || date.isAfter(LocalDate.now(clock.withZone(ZoneId.of("Asia/Seoul"))))) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR);
        }
    }

    private void validateDatesAndRegion(CaseDtos.Input input) {
        validateDate(input.birthDate()); validateDate(input.firstRegisteredAt());
        if (!repository.dongExists(input.dongCode())) throw new ApiException(ErrorCode.VALIDATION_ERROR);
    }
    private void validateSearch(CaseDtos.Search s) {
        if ((s.registeredFrom()!=null && s.registeredTo()!=null && s.registeredFrom().isAfter(s.registeredTo()))
                || (s.recordedFrom()!=null && s.recordedTo()!=null && s.recordedFrom().isAfter(s.recordedTo()))
                || (s.sidoCode()!=null && s.sigunguCode()!=null && !s.sigunguCode().startsWith(s.sidoCode()))
                || (s.dongCode()!=null && s.sidoCode()!=null && !s.dongCode().startsWith(s.sidoCode()))
                || (s.dongCode()!=null && s.sigunguCode()!=null && !s.dongCode().startsWith(s.sigunguCode()))) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR);
        }
    }
}
