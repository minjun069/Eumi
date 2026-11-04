package com.eumi.backend.resources;

import java.util.*;
import com.eumi.backend.auth.login.AuthService;
import com.eumi.backend.auth.login.LoginUser;
import com.eumi.backend.common.error.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional(readOnly=true)
public class ResourceService {
    private static final Logger log=LoggerFactory.getLogger(ResourceService.class);
    private static final Set<String> AGES=Set.of("청소년","청년","중장년","노년","무관");
    private final ResourceRepository repository;
    private final AuthService auth;
    public ResourceService(ResourceRepository repository,AuthService auth) { this.repository=repository;this.auth=auth; }
    private LoginUser requireUser(long member) {
        var user=auth.currentUser(member);
        if(user.mustChangePassword()) throw new ApiException(ErrorCode.PASSWORD_CHANGE_REQUIRED);
        return user;
    }
    public ResourceDtos.Page search(long member,ResourceDtos.Search s) {
        requireUser(member);
        var fields=new ArrayList<ApiErrorResponse.FieldError>();
        if(s.capacityMin()!=null && s.capacityMax()!=null && s.capacityMin()>s.capacityMax()) field(fields,"capacityMax");
        if(s.sidoCode()!=null && s.sigunguCode()!=null && !s.sigunguCode().startsWith(s.sidoCode())) field(fields,"sigunguCode");
        if(s.dongCode()!=null && ((s.sidoCode()!=null && !s.dongCode().startsWith(s.sidoCode()))
                || (s.sigunguCode()!=null && !s.dongCode().startsWith(s.sigunguCode())))) field(fields,"dongCode");
        validate(fields); return repository.search(s);
    }
    public ResourceDtos.Detail detail(long member,long id) {
        requireUser(member); var detail=repository.detail(id,member).orElseThrow(()->new ApiException(ErrorCode.NOT_FOUND));
        if(detail.manager().withdrawn() && detail.status().equals("진행 중")) {
            log.error("Resource integrity failure: ongoing resource has withdrawn manager resourceId={}",id);
            throw new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
        }
        return detail;
    }
    @Transactional
    public ResourceDtos.Created create(long member,ResourceDtos.Input input) {
        requireUser(member);validateInput(input);lockWriter(member,input.managerMemberId());
        return new ResourceDtos.Created(repository.insert(input));
    }
    @Transactional
    public void update(long member,long id,ResourceDtos.Input input) {
        requireUser(member);preflight(member,id);validateInput(input);
        lockWriter(member,input.managerMemberId());requireLockedManager(member,id);repository.update(id,input);
    }
    @Transactional
    public void delete(long member,long id) {
        requireUser(member);preflight(member,id);lockWriter(member,member);requireLockedManager(member,id);repository.delete(id);
    }
    private void preflight(long member,long id) {
        long manager=repository.visibleManager(id).orElseThrow(()->new ApiException(ErrorCode.NOT_FOUND));
        if(manager!=member) throw new ApiException(ErrorCode.FORBIDDEN);
    }
    private void requireLockedManager(long member,long id) {
        var row=repository.lock(id).orElseThrow(()->new ApiException(ErrorCode.NOT_FOUND));
        if(row.deleted()) throw new ApiException(ErrorCode.NOT_FOUND);
        if(row.managerId()!=member) throw new ApiException(ErrorCode.FORBIDDEN);
    }
    // 공통 가이드: 기관 → 같은 기관 회원(ID순) → 자원. 획득 후 최신 활성 상태·담당자를 재확인한다.
    private void lockWriter(long member,long manager) {
        var before=requireUser(member);repository.lockOrganization(before.orgId());
        var ids=new TreeSet<>(List.of(member,manager));var active=repository.lockActiveMembers(before.orgId(),ids);
        var user=requireUser(member);
        if(user.orgId()!=before.orgId()) throw new ApiException(ErrorCode.FORBIDDEN);
        if(!active.contains(manager)) throw invalid("managerMemberId");
    }
    private void validateInput(ResourceDtos.Input i) {
        var fields=new ArrayList<ApiErrorResponse.FieldError>();
        if(!repository.sigunguExists(i.sigunguCode())) field(fields,"sigunguCode");
        if(i.dongCode()!=null && (!i.dongCode().startsWith(i.sigunguCode()) || !repository.dongExists(i.dongCode()))) field(fields,"dongCode");
        if(i.periodStart().getYear()<1 || i.periodStart().getYear()>9999) field(fields,"periodStart");
        if(i.periodEnd().getYear()<1 || i.periodEnd().getYear()>9999 || i.periodStart().isAfter(i.periodEnd())) field(fields,"periodEnd");
        if(i.supportAgeGroups().stream().anyMatch(age->age==null || !AGES.contains(age))
                || (i.supportAgeGroups().contains("무관") && i.supportAgeGroups().size()!=1)) field(fields,"supportAgeGroups");
        validate(fields);
    }
    private static void field(List<ApiErrorResponse.FieldError> fields,String name) {
        fields.add(new ApiErrorResponse.FieldError(name,"입력값을 확인해 주세요."));
    }
    private static void validate(List<ApiErrorResponse.FieldError> fields) {
        if(!fields.isEmpty()) throw new ApiException(ErrorCode.VALIDATION_ERROR,fields);
    }
    private static ApiException invalid(String field) {
        return new ApiException(ErrorCode.VALIDATION_ERROR,List.of(new ApiErrorResponse.FieldError(field,"입력값을 확인해 주세요.")));
    }
}
