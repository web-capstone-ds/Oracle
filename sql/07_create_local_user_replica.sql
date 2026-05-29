-- Task AU3: 모바일 오퍼레이터 인증 복제본 테이블
CREATE TABLE IF NOT EXISTS local_user_replica (
  operator_id   TEXT PRIMARY KEY,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL,
  active        BOOLEAN NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL,
  synced_at     TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE local_user_replica IS
  'Online Web Backend users 테이블의 단방향 복제본. Auth 서비스 로그인 검증 전용.';
