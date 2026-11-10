package com.eumi.backend.mypage;

import java.util.*;
import com.eumi.backend.auth.password.PasswordChangeRepository;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class WithdrawalRepository {
    private final JdbcTemplate jdbc;
    public WithdrawalRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    // 활성 공동 담당자가 없는지 판정한다. 탈퇴 회원의 연결은 공동 담당으로 세지 않는다.
    private static final String SOLE = """
            NOT EXISTS (SELECT 1 FROM public.case_manager other
                JOIN public.member m ON m.member_id=other.member_id
                WHERE other.case_id=c.case_id AND other.member_id<>? AND m.withdrawn_at IS NULL)
            """;
    public List<WithdrawalDtos.SoleCase> soleCases(long member) {
        return jdbc.query("""
                SELECT c.case_id,c.management_no,c.name,c.age_group,c.dong_name,c.last_recorded_at
                FROM public.v_case_summary c JOIN public.case_manager mine ON mine.case_id=c.case_id
                WHERE mine.member_id=? AND
                """ + SOLE + " ORDER BY c.management_no,c.case_id", (rs,row) -> new WithdrawalDtos.SoleCase(
                rs.getLong(1),rs.getString(2),rs.getString(3),rs.getString(4),rs.getString(5),rs.getObject(6,java.time.LocalDate.class)),member,member);
    }
    public long sharedCaseCount(long member) {
        return jdbc.queryForObject("SELECT count(*) FROM public.case_record c JOIN public.case_manager mine ON mine.case_id=c.case_id "
                + "WHERE mine.member_id=? AND NOT (" + SOLE + ")",Long.class,member,member);
    }
    public Set<Long> soleCaseIds(long member) {
        return new HashSet<>(jdbc.query("SELECT c.case_id FROM public.case_record c JOIN public.case_manager mine ON mine.case_id=c.case_id "
                + "WHERE mine.member_id=? AND " + SOLE,(rs,row)->rs.getLong(1),member,member));
    }
    public List<WithdrawalDtos.Successor> successors(long org, long member) {
        return jdbc.query("SELECT member_id,name,title FROM public.member WHERE org_id=? AND member_id<>? AND withdrawn_at IS NULL ORDER BY name,member_id",
                (rs,row)->new WithdrawalDtos.Successor(rs.getLong(1),rs.getString(2),rs.getString(3)),org,member);
    }
    public List<WithdrawalDtos.OngoingResource> ongoingResources(long member) {
        return jdbc.query("SELECT resource_id,resource_name,period_end FROM public.v_resource_summary WHERE manager_member_id=? AND status='진행 중' ORDER BY resource_id",
                (rs,row)->new WithdrawalDtos.OngoingResource(rs.getLong(1),rs.getString(2),rs.getObject(3,java.time.LocalDate.class)),member);
    }
    public long endedResourceCount(long member) {
        return jdbc.queryForObject("SELECT count(*) FROM public.v_resource_summary WHERE manager_member_id=? AND status='종료'",Long.class,member);
    }
    public long conversationCount(long member) {
        return jdbc.queryForObject("SELECT count(*) FROM public.ai_conversation WHERE member_id=? AND delete_scheduled_at>current_date",Long.class,member);
    }
    public List<UUID> activeConversations(long member) {
        return jdbc.query("""
                SELECT c.conversation_id FROM public.ai_conversation c WHERE c.member_id=? AND EXISTS (
                    SELECT 1 FROM public.ai_message q WHERE q.conversation_id=c.conversation_id AND q.status='질문'
                    AND NOT EXISTS (SELECT 1 FROM public.ai_message e WHERE e.question_id=q.message_id AND e.status IN ('완료','실패','취소')))
                ORDER BY c.conversation_id
                """,(rs,row)->rs.getObject(1,UUID.class),member);
    }
    public void lockOrganization(long org) {
        jdbc.queryForObject("SELECT org_id FROM public.organization WHERE org_id=? FOR UPDATE",Long.class,org);
    }
    public record LockedMember(long memberId, PasswordChangeRepository.Account account) { }
    public List<LockedMember> lockMembers(SortedSet<Long> members) {
        String placeholders = String.join(",",Collections.nCopies(members.size(),"?"));
        return jdbc.query("SELECT member_id,org_id,password_hash,temp_password_expires_at,withdrawn_at FROM public.member WHERE member_id IN ("
                + placeholders + ") ORDER BY member_id FOR UPDATE",(rs,row)->{
            var expiry = rs.getObject(4,java.time.OffsetDateTime.class);
            return new LockedMember(rs.getLong(1),new PasswordChangeRepository.Account(rs.getLong(2),rs.getString(3),
                    expiry == null ? null : expiry.toInstant(),rs.getObject(5) != null));
        },members.toArray());
    }
    public void lockCases(long member) {
        jdbc.query("""
                SELECT c.case_id FROM public.case_record c JOIN public.case_manager mine ON mine.case_id=c.case_id
                WHERE mine.member_id=? ORDER BY c.case_id FOR UPDATE OF c
                """,(rs,row)->rs.getLong(1),member);
    }
    public void lockResources(long member) {
        jdbc.query("SELECT resource_id FROM public.welfare_resource WHERE manager_member_id=? AND deleted_at IS NULL ORDER BY resource_id FOR UPDATE",
                (rs,row)->rs.getLong(1),member);
    }
    public void transferCase(WithdrawalDtos.Transfer transfer) {
        jdbc.update("INSERT INTO public.case_manager(case_id,member_id) VALUES (?,?) ON CONFLICT DO NOTHING",transfer.caseId(),transfer.newManagerMemberId());
    }
    public void deleteCaseLinks(long member) { jdbc.update("DELETE FROM public.case_manager WHERE member_id=?",member); }
    public int transferResource(long member, WithdrawalDtos.ResourceTransfer transfer) {
        return jdbc.update("UPDATE public.welfare_resource SET manager_member_id=?,updated_at=now() WHERE resource_id=? AND manager_member_id=? AND deleted_at IS NULL",
                transfer.newManagerMemberId(),transfer.resourceId(),member);
    }
    public void deleteConversations(long member) { jdbc.update("DELETE FROM public.ai_conversation WHERE member_id=?",member); }
    public int withdrawMember(long member) {
        return jdbc.update("UPDATE public.member SET withdrawn_at=now(),updated_at=now() WHERE member_id=? AND withdrawn_at IS NULL",member);
    }
}
