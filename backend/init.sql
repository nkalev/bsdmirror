-- BSD Mirrors Database Initialization
-- This script runs on first database startup

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Insert default mirrors (will be updated by sync service)
INSERT INTO mirrors (name, mirror_type, upstream_url, local_path, enabled, status)
VALUES 
    ('FreeBSD', 'freebsd', 'rsync://ftp.freebsd.org/FreeBSD/', '/data/mirrors/freebsd/pub/FreeBSD', true, 'active'),
    ('NetBSD', 'netbsd', 'rsync://ftp.netbsd.org/pub/NetBSD/', '/data/mirrors/netbsd/pub/NetBSD', true, 'active'),
    ('OpenBSD', 'openbsd', 'rsync://ftp.openbsd.org/pub/OpenBSD/', '/data/mirrors/openbsd/pub/OpenBSD', true, 'active')
ON CONFLICT (name) DO NOTHING;

-- Note: Admin user is created by the backend on first startup
