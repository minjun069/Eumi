package com.eumi.backend.reference;

import java.util.List;
import com.eumi.backend.auth.login.AuthService;
import com.eumi.backend.auth.login.LoginUser;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional(readOnly = true)
public class ReferenceDataService {
    private static final Logger log = LoggerFactory.getLogger(ReferenceDataService.class);
    private final ReferenceDataRepository repository;
    private final AuthService auth;

    public ReferenceDataService(ReferenceDataRepository repository, AuthService auth) {
        this.repository = repository;
        this.auth = auth;
    }

    public List<ReferenceDataDtos.SidoItem> sidos(long memberId) {
        requireUser(memberId);
        var result = repository.sidos();
        for (var sido : result) {
            if (sido.sidoName() == null || sido.sidoName().isBlank()) {
                log.warn("Missing sido name mapping sidoCode={}", sido.sidoCode());
                throw new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
            }
        }
        return result;
    }

    public List<ReferenceDataDtos.SigunguItem> sigungus(long memberId, String sidoCode) {
        requireUser(memberId);
        if (!repository.sidoExists(sidoCode)) throw new ApiException(ErrorCode.NOT_FOUND);
        return repository.sigungus(sidoCode);
    }

    public List<ReferenceDataDtos.DongItem> dongs(long memberId, String sigunguCode) {
        requireUser(memberId);
        if (!repository.sigunguExists(sigunguCode)) throw new ApiException(ErrorCode.NOT_FOUND);
        return repository.dongs(sigunguCode);
    }

    public List<ReferenceDataDtos.MemberOption> members(long memberId) {
        return repository.activeMembers(requireUser(memberId).orgId());
    }

    private LoginUser requireUser(long memberId) {
        var user = auth.currentUser(memberId);
        if (user.mustChangePassword()) throw new ApiException(ErrorCode.PASSWORD_CHANGE_REQUIRED);
        return user;
    }
}
