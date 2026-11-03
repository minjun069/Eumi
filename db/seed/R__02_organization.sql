-- 가상 시연 기관. ID는 IDENTITY로 발급해 운영 시퀀스를 수동 변경하지 않는다.
-- Flyway repeatable seed는 직렬 실행한다. 기존 기관 행은 수정하지 않는다.
-- 기관 중복은 WHERE NOT EXISTS로 방지하고, 시퀀스 불일치에 따른 PK 충돌은 오류로 드러낸다.
INSERT INTO organization (org_name, jurisdiction_sigungu_code, official_domain)
SELECT seed.org_name, seed.sigungu_code, seed.official_domain
FROM (VALUES
    ('이음이 강남 시연기관', '11680', 'demo-gangnam.eumi.test'),
    ('이음이 춘천 시연기관', '51110', 'demo-chuncheon.eumi.test')
) AS seed(org_name, sigungu_code, official_domain)
WHERE NOT EXISTS (
    SELECT 1 FROM organization existing
    WHERE existing.org_name = seed.org_name
      AND existing.jurisdiction_sigungu_code = seed.sigungu_code
      AND existing.official_domain = seed.official_domain
);
