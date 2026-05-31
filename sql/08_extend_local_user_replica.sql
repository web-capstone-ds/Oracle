-- Web Backend users 프로필 필드 확장 반영 (단방향 복제본).
-- AuthSnapshotResponse.SnapshotUserDto 에 추가된 name/department/phone 수용.
ALTER TABLE local_user_replica ADD COLUMN IF NOT EXISTS name       TEXT;
ALTER TABLE local_user_replica ADD COLUMN IF NOT EXISTS department TEXT;
ALTER TABLE local_user_replica ADD COLUMN IF NOT EXISTS phone      TEXT;
