-- PBKDF2: 기본 id=pbkdf2, Spring Security v5_8 기본값. 평문은 저장하지 않는다.
-- 탈퇴 상태·기존 암호·수정된 프로필도 ON CONFLICT DO NOTHING으로 보존한다.
-- 이메일 중복만 건너뛴다. 시퀀스 불일치에 따른 PK 충돌은 오류로 드러낸다.
INSERT INTO member (org_id, email_normalized, name, title, password_hash)
SELECT organization.org_id, seed.email, seed.name, '사회복지사', seed.password_hash
FROM (VALUES
    ('demo1@demo-gangnam.eumi.test', '강남 시연담당 1', 'demo-gangnam.eumi.test', '이음이 강남 시연기관', '11680', '{pbkdf2}a6f94b4ba82ca95d553b5d32324b9dd3e6c3a5f9b2a1029cb34d3e33807e80f24b84966da0fb797c0c0b13b3864f364c'),
    ('demo2@demo-gangnam.eumi.test', '강남 시연담당 2', 'demo-gangnam.eumi.test', '이음이 강남 시연기관', '11680', '{pbkdf2}83662aec3accd5000b51a2086d7893b0733c956445b81134b51169aede5c7e82ee633a1d78a9f0ef025077bd49e425c2'),
    ('demo1@demo-chuncheon.eumi.test', '춘천 시연담당 1', 'demo-chuncheon.eumi.test', '이음이 춘천 시연기관', '51110', '{pbkdf2}250a468aa743e381bcf1e882c3772589c028f9f81d3672c3299e0a633159300a7ebfc383775e4366b44613daf7edc0a9'),
    ('demo2@demo-chuncheon.eumi.test', '춘천 시연담당 2', 'demo-chuncheon.eumi.test', '이음이 춘천 시연기관', '51110', '{pbkdf2}42a170760f67a8839c36d33259d35ce88cc3d23522913f1f1303b1ca0d1eb001af7291980c25ce977db4b79354f2d8f0')
) AS seed(email, name, domain, org_name, sigungu_code, password_hash)
JOIN LATERAL (
    SELECT org_id FROM organization
    WHERE official_domain = seed.domain AND org_name = seed.org_name
      AND jurisdiction_sigungu_code = seed.sigungu_code
    ORDER BY org_id LIMIT 1
) organization ON true
ON CONFLICT (email_normalized) DO NOTHING;
