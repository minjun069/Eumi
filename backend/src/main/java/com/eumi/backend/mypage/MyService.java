package com.eumi.backend.mypage;

import com.eumi.backend.auth.login.*;
import com.eumi.backend.common.error.*;
import com.eumi.backend.resources.ResourceRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional(readOnly=true)
public class MyService {
    private final MyRepository repository;
    private final ResourceRepository resources;
    private final AuthService auth;
    public MyService(MyRepository repository,ResourceRepository resources,AuthService auth) {
        this.repository=repository;this.resources=resources;this.auth=auth;
    }
    private LoginUser requireUser(long member) {
        var user=auth.currentUser(member);
        if(user.mustChangePassword())throw new ApiException(ErrorCode.PASSWORD_CHANGE_REQUIRED);
        return user;
    }
    public MyDtos.MyInfo info(long member) {requireUser(member);return repository.info(member);}
    @Transactional
    public MyDtos.MyInfo patch(long member,MyDtos.Patch patch) {
        var before=requireUser(member);repository.lockOrganization(before.orgId());repository.lockMember(before.orgId(),member);
        var current=requireUser(member);
        if(current.orgId()!=before.orgId())throw new ApiException(ErrorCode.FORBIDDEN);
        repository.patch(member,patch);return repository.info(member);
    }
    public MyDtos.MyResources resources(long member) {
        requireUser(member);var items=resources.managedBy(member);return new MyDtos.MyResources(items.size(),items);
    }
}
