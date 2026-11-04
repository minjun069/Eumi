package com.eumi.backend.cases;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ConsultationRepository {
    private static final String SELECT = "SELECT c.*,m.name AS recorder_name FROM public.consultation c "
            + "JOIN public.member m ON m.member_id=c.recorder_member_id ";
    private final JdbcTemplate jdbc;
    public ConsultationRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public List<ConsultationDtos.ListItem> list(long caseId) {
        return jdbc.query(SELECT + "WHERE c.case_id=? ORDER BY c.consulted_at DESC,c.consultation_id DESC", this::item, caseId);
    }
    private ConsultationDtos.ListItem item(ResultSet rs, int row) throws SQLException {
        return new ConsultationDtos.ListItem(rs.getLong("consultation_id"), rs.getObject("consulted_at", LocalDate.class),
                rs.getString("purpose"), rs.getString("category"), rs.getString("category_etc"), rs.getString("recorder_name"));
    }
    public Optional<ConsultationDtos.Detail> detail(long caseId, long id) {
        return jdbc.query(SELECT + "WHERE c.case_id=? AND c.consultation_id=?", (rs, row) -> {
            var item = item(rs, row);
            return new ConsultationDtos.Detail(item.consultationId(), item.consultedAt(), item.purpose(), item.category(),
                    item.categoryEtc(), item.recorderName(), rs.getString("content"), rs.getLong("recorder_member_id"));
        }, caseId, id).stream().findFirst();
    }
    public long insert(long caseId, long recorder, ConsultationDtos.Input input) {
        return jdbc.queryForObject("""
                INSERT INTO public.consultation(case_id,consulted_at,purpose,category,category_etc,content,recorder_member_id)
                VALUES (?,?,?,?,?,?,?) RETURNING consultation_id
                """, Long.class, caseId, input.consultedAt(), input.purpose(), input.category(), input.categoryEtc(), input.content(), recorder);
    }
    public int update(long caseId, long id, ConsultationDtos.Input input) {
        return jdbc.update("""
                UPDATE public.consultation SET consulted_at=?,purpose=?,category=?,category_etc=?,content=?,updated_at=now()
                WHERE case_id=? AND consultation_id=?
                """, input.consultedAt(), input.purpose(), input.category(), input.categoryEtc(), input.content(), caseId, id);
    }
    public int delete(long caseId, long id) {
        return jdbc.update("DELETE FROM public.consultation WHERE case_id=? AND consultation_id=?", caseId, id);
    }
}
