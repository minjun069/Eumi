package com.eumi.backend.cases;

import java.util.List;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional(readOnly = true)
public class ConsultationService {
    private final CaseService cases;
    private final ConsultationRepository repository;
    public ConsultationService(CaseService cases, ConsultationRepository repository) { this.cases = cases; this.repository = repository; }

    public List<ConsultationDtos.ListItem> list(long member, long caseId) {
        cases.requireAccess(cases.requireUser(member), caseId, false); return repository.list(caseId);
    }
    public ConsultationDtos.Detail detail(long member, long caseId, long id) {
        cases.requireAccess(cases.requireUser(member), caseId, false);
        return repository.detail(caseId, id).orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND));
    }

    @Transactional
    public ConsultationDtos.Created create(long member, long caseId, ConsultationDtos.Input input) {
        writeAccess(member, caseId); validate(input);
        return new ConsultationDtos.Created(repository.insert(caseId, member, input));
    }
    @Transactional
    public void update(long member, long caseId, long id, ConsultationDtos.Input input) {
        writeAccess(member, caseId); validate(input);
        if (repository.update(caseId, id, input) == 0) throw new ApiException(ErrorCode.NOT_FOUND);
    }
    @Transactional
    public void delete(long member, long caseId, long id) {
        writeAccess(member, caseId);
        if (repository.delete(caseId, id) == 0) throw new ApiException(ErrorCode.NOT_FOUND);
    }
    private void writeAccess(long member, long caseId) {
        var user = cases.lockWriter(member, List.of(member), ErrorCode.FORBIDDEN);
        cases.requireAccess(user, caseId, true);
    }
    private void validate(ConsultationDtos.Input input) {
        cases.validateDate(input.consultedAt());
        if ("기타".equals(input.category()) && (input.categoryEtc() == null || input.categoryEtc().isBlank())) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR);
        }
    }
}
