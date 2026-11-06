package com.eumi.backend.resources;

import java.sql.*;
import java.time.LocalDate;
import java.util.*;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.*;
import org.springframework.jdbc.support.SqlArrayValue;
import org.springframework.stereotype.Repository;

@Repository
public class ResourceRepository {
    private final JdbcTemplate jdbc;
    private final NamedParameterJdbcTemplate named;
    private static final Map<String,String> SORTS=Map.of("resourceName","resource_name","capacity","capacity",
            "periodEnd","period_end","fee","fee");
    public ResourceRepository(JdbcTemplate jdbc) { this.jdbc=jdbc; named=new NamedParameterJdbcTemplate(jdbc); }

    public boolean sigunguExists(String code) {
        return Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM public.v_sigungu WHERE sigungu_code=?)",Boolean.class,code));
    }
    public boolean dongExists(String code) {
        return Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM public.dim_region WHERE adm_cd10=?)",Boolean.class,code));
    }
    public void lockOrganization(long org) {
        jdbc.queryForObject("SELECT org_id FROM public.organization WHERE org_id=? FOR UPDATE",Long.class,org);
    }
    public Set<Long> lockActiveMembers(long org,Collection<Long> ids) {
        return new HashSet<>(named.query("""
                SELECT member_id,withdrawn_at FROM public.member
                WHERE org_id=:org AND member_id IN (:ids) ORDER BY member_id FOR UPDATE
                """,new MapSqlParameterSource("org",org).addValue("ids",ids),
                (rs,row)->rs.getObject("withdrawn_at")==null ? rs.getLong("member_id") : null)
                .stream().filter(Objects::nonNull).toList());
    }
    public Optional<Long> visibleManager(long id) {
        return jdbc.query("SELECT manager_member_id FROM public.v_resource_summary WHERE resource_id=?",
                (rs,row)->rs.getLong(1),id).stream().findFirst();
    }
    public Optional<LockedResource> lock(long id) {
        return jdbc.query("SELECT manager_member_id,deleted_at FROM public.welfare_resource WHERE resource_id=? FOR UPDATE",
                (rs,row)->new LockedResource(rs.getLong(1),rs.getObject(2)!=null),id).stream().findFirst();
    }
    public record LockedResource(long managerId,boolean deleted) { }

    public List<ResourceDtos.ListItem> managedBy(long member) {
        return jdbc.query("""
                SELECT * FROM public.v_resource_summary WHERE manager_member_id=?
                ORDER BY status_order ASC,period_end ASC,resource_id ASC
                """,this::listItem,member);
    }

    public ResourceDtos.Page search(ResourceDtos.Search s) {
        var p=new MapSqlParameterSource(); var where=new StringBuilder(" FROM public.v_resource_summary WHERE true");
        add(where,p,"sido","sido_code",s.sidoCode(),"=");
        add(where,p,"sigungu","sigungu_code",s.sigunguCode(),"=");
        if(s.dongCode()!=null) {
            where.append(" AND (dong_code=:dong OR (dong_code IS NULL AND sigungu_code=left(:dong,5)))");p.addValue("dong",s.dongCode());
        }
        if(!s.ageGroup().equals("전체")) {
            where.append(" AND (:age=ANY(support_age_groups) OR '무관'=ANY(support_age_groups))");p.addValue("age",s.ageGroup());
        }
        if(!s.gender().equals("전체")) {
            where.append(" AND support_gender IN (:gender,'무관')");p.addValue("gender",s.gender());
        }
        add(where,p,"min","capacity",s.capacityMin(),">="); add(where,p,"max","capacity",s.capacityMax(),"<=");
        if(!s.resourceName().isEmpty()) {
            where.append(" AND resource_name LIKE :name ESCAPE '!'");p.addValue("name",literalLike(s.resourceName()));
        }
        if(!s.managerName().isEmpty()) {
            where.append(" AND manager_withdrawn=false AND manager_name LIKE :manager ESCAPE '!'");
            p.addValue("manager",literalLike(s.managerName()));
        }
        long count=named.queryForObject("SELECT count(*)"+where,p,Long.class);
        long pages=count==0 ? 0 : (count-1)/s.size()+1; long page=pages==0 ? 1 : Math.min(s.page(),pages);
        String sort=SORTS.get(s.sort());
        if(sort==null || !Set.of("asc","desc").contains(s.direction())) throw new ApiException(ErrorCode.VALIDATION_ERROR);
        p.addValue("limit",s.size()).addValue("offset",(page-1)*s.size());
        var items=named.query("SELECT *"+where+" ORDER BY status_order ASC, "+sort+" "+s.direction()
                +", period_end ASC, resource_id ASC LIMIT :limit OFFSET :offset",p,this::listItem);
        return new ResourceDtos.Page(count,page,s.size(),pages,items);
    }
    private static String literalLike(String s) { return "%"+s.replace("!","!!").replace("%","!%").replace("_","!_")+"%"; }
    private static void add(StringBuilder sql,MapSqlParameterSource p,String key,String column,Object value,String operator) {
        if(value!=null) { sql.append(" AND ").append(column).append(operator).append(':').append(key);p.addValue(key,value); }
    }
    private ResourceDtos.ListItem listItem(ResultSet rs,int row) throws SQLException {
        if(rs.getString("sigungu_name")==null || rs.getString("sido_name")==null
                || (rs.getString("dong_code")!=null && rs.getString("dong_name")==null)) throw new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
        return new ResourceDtos.ListItem(rs.getLong("resource_id"),rs.getString("resource_name"),rs.getString("operating_org_name"),
                rs.getString("target"),rs.getInt("capacity"),rs.getString("sigungu_name"),rs.getString("dong_name"),
                rs.getObject("period_start",LocalDate.class),rs.getObject("period_end",LocalDate.class),rs.getInt("fee"),rs.getString("status"));
    }
    public Optional<ResourceDtos.Detail> detail(long id,long caller) {
        return jdbc.query("SELECT * FROM public.v_resource_summary WHERE resource_id=?",(rs,row)->{
            var i=listItem(rs,row); boolean withdrawn=rs.getBoolean("manager_withdrawn");long manager=rs.getLong("manager_member_id");
            List<String> ages; var array=rs.getArray("support_age_groups");
            try { ages=List.of((String[])array.getArray()); } finally { array.free(); }
            return new ResourceDtos.Detail(i.resourceId(),i.resourceName(),i.operatingOrgName(),i.target(),i.capacity(),
                    i.sigunguName(),i.dongName(),i.periodStart(),i.periodEnd(),i.fee(),i.status(),ages,rs.getString("support_gender"),
                    rs.getString("sido_code"),rs.getString("sido_name"),rs.getString("sigungu_code"),rs.getString("dong_code"),
                    rs.getBoolean("auto_ended"),rs.getObject("actual_participants",Integer.class),rs.getString("support_content"),
                    rs.getString("apply_method"),new ResourceDtos.Manager(manager,rs.getString("manager_name"),rs.getString("manager_title"),
                    rs.getString("manager_org_name"),withdrawn),!withdrawn && manager==caller,rs.getString("manual_status"));
        },id).stream().findFirst();
    }
    private MapSqlParameterSource parameters(ResourceDtos.Input i) {
        return new MapSqlParameterSource("name",i.resourceName()).addValue("operatingOrg",i.operatingOrgName())
                .addValue("target",i.target()).addValue("ages",new SqlArrayValue("text",i.supportAgeGroups().toArray()))
                .addValue("gender",i.supportGender()).addValue("sigungu",i.sigunguCode()).addValue("dong",i.dongCode())
                .addValue("start",i.periodStart()).addValue("end",i.periodEnd()).addValue("fee",i.fee()).addValue("status",i.status())
                .addValue("manager",i.managerMemberId()).addValue("capacity",i.capacity()).addValue("actual",i.actualParticipants())
                .addValue("content",i.supportContent()).addValue("method",i.applyMethod());
    }
    public long insert(ResourceDtos.Input i) {
        return named.queryForObject("""
                INSERT INTO public.welfare_resource(resource_name,operating_org_name,target,support_age_groups,support_gender,
                sigungu_code,dong_code,period_start,period_end,fee,manual_status,manager_member_id,capacity,actual_participants,support_content,apply_method)
                VALUES (:name,:operatingOrg,:target,:ages,:gender,:sigungu,:dong,:start,:end,:fee,:status,:manager,:capacity,:actual,:content,:method)
                RETURNING resource_id
                """,parameters(i),Long.class);
    }
    public void update(long id,ResourceDtos.Input i) {
        named.update("""
                UPDATE public.welfare_resource SET resource_name=:name,operating_org_name=:operatingOrg,target=:target,
                support_age_groups=:ages,support_gender=:gender,sigungu_code=:sigungu,dong_code=:dong,period_start=:start,period_end=:end,
                fee=:fee,manual_status=:status,manager_member_id=:manager,capacity=:capacity,actual_participants=:actual,
                support_content=:content,apply_method=:method,updated_at=now() WHERE resource_id=:id
                """,parameters(i).addValue("id",id));
    }
    public void delete(long id) { jdbc.update("UPDATE public.welfare_resource SET deleted_at=now() WHERE resource_id=?",id); }
}
