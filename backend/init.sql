-- BSD Mirrors Database Initialization
-- This script runs on first database startup

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Note: Admin user and default mirrors are seeded by the backend on first startup.
-- See backend/app/main.py lifespan() for the seeding logic.
