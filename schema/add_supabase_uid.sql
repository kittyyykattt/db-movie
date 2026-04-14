-- Links MovieTrack "Users" rows to Supabase Auth (auth.users.id).
-- Run once against your project database (e.g. Supabase SQL editor or psql).

ALTER TABLE "Users" ADD COLUMN IF NOT EXISTS supabase_uid UUID UNIQUE;

CREATE INDEX IF NOT EXISTS idx_users_supabase_uid ON "Users" (supabase_uid)
  WHERE supabase_uid IS NOT NULL;
