-- Simple User Authentication with Roles
-- Users: first letter + lastname (e.g., rmontoni for Robin Montoni)
-- Default password for users: @mst123
-- Admin: admin / !pcr123

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user',  -- 'user' or 'admin'
    employee_name VARCHAR(100),  -- Maps to employee_name in transcripts
    is_active BOOLEAN DEFAULT TRUE,
    must_change_password BOOLEAN DEFAULT TRUE,  -- Force password change on first login
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP,
    password_changed_at TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_employee ON users(employee_name);

-- Insert generic admin user (password: !pcr123) - admin doesn't need to change password
INSERT INTO users (username, password_hash, display_name, role, employee_name, must_change_password)
VALUES ('admin', 'pbkdf2:sha256:600000$admin$!pcr123', 'Administrator', 'admin', NULL, FALSE)
ON CONFLICT (username) DO NOTHING;

-- ADMIN USERS (jblair, sabbey, lrogers, bkubicek) - password: !pcr123, no password change required
INSERT INTO users (username, password_hash, display_name, role, employee_name, must_change_password)
VALUES ('jblair', 'pbkdf2:sha256:600000$admin$!pcr123', 'J Blair', 'admin', 'J Blair', FALSE)
ON CONFLICT (username) DO NOTHING;

INSERT INTO users (username, password_hash, display_name, role, employee_name, must_change_password)
VALUES ('sabbey', 'pbkdf2:sha256:600000$admin$!pcr123', 'Stacy Abbey', 'admin', 'Stacy Abbey', FALSE)
ON CONFLICT (username) DO NOTHING;

INSERT INTO users (username, password_hash, display_name, role, employee_name, must_change_password)
VALUES ('lrogers', 'pbkdf2:sha256:600000$admin$!pcr123', 'L Rogers', 'admin', 'L Rogers', FALSE)
ON CONFLICT (username) DO NOTHING;

INSERT INTO users (username, password_hash, display_name, role, employee_name, must_change_password)
VALUES ('bkubicek', 'pbkdf2:sha256:600000$admin$!pcr123', 'B Kubicek', 'admin', 'B Kubicek', FALSE)
ON CONFLICT (username) DO NOTHING;

-- Insert regular users based on employee names from the system
-- Format: first letter + lastname, password: @mst123
-- These will be created from the canonical employee list

-- Robin Montoni
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('rmontoni', 'pbkdf2:sha256:600000$user$@mst123', 'Robin Montoni', 'user', 'Robin Montoni')
ON CONFLICT (username) DO NOTHING;

-- Stacy Abbeyquaye
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('sabbeyquaye', 'pbkdf2:sha256:600000$user$@mst123', 'Stacy Abbeyquaye', 'user', 'Stacy Abbeyquaye')
ON CONFLICT (username) DO NOTHING;

-- Dan Gallo
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('dgallo', 'pbkdf2:sha256:600000$user$@mst123', 'Dan Gallo', 'user', 'Dan Gallo')
ON CONFLICT (username) DO NOTHING;

-- Marissa Kall
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('mkall', 'pbkdf2:sha256:600000$user$@mst123', 'Marissa Kall', 'user', 'Marissa Kall')
ON CONFLICT (username) DO NOTHING;

-- Sarah Nickel
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('snickel', 'pbkdf2:sha256:600000$user$@mst123', 'Sarah Nickel', 'user', 'Sarah Nickel')
ON CONFLICT (username) DO NOTHING;

-- Jodi O'Donnell
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('jodonnell', 'pbkdf2:sha256:600000$user$@mst123', 'Jodi O''Donnell', 'user', 'Jodi O''Donnell')
ON CONFLICT (username) DO NOTHING;

-- Kathi Gibbons
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('kgibbons', 'pbkdf2:sha256:600000$user$@mst123', 'Kathi Gibbons', 'user', 'Kathi Gibbons')
ON CONFLICT (username) DO NOTHING;

-- Kim Rocco
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('krocco', 'pbkdf2:sha256:600000$user$@mst123', 'Kim Rocco', 'user', 'Kim Rocco')
ON CONFLICT (username) DO NOTHING;

-- Tammy Scherzer
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('tscherzer', 'pbkdf2:sha256:600000$user$@mst123', 'Tammy Scherzer', 'user', 'Tammy Scherzer')
ON CONFLICT (username) DO NOTHING;

-- Lori Geuder
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('lgeuder', 'pbkdf2:sha256:600000$user$@mst123', 'Lori Geuder', 'user', 'Lori Geuder')
ON CONFLICT (username) DO NOTHING;

-- Mike Buss
INSERT INTO users (username, password_hash, display_name, role, employee_name)
VALUES ('mbuss', 'pbkdf2:sha256:600000$user$@mst123', 'Mike Buss', 'user', 'Mike Buss')
ON CONFLICT (username) DO NOTHING;

-- Comments
COMMENT ON TABLE users IS 'Simple user authentication with role-based access';
COMMENT ON COLUMN users.role IS 'user = sees own data only, admin = sees all data';
COMMENT ON COLUMN users.employee_name IS 'Maps to employee_name in transcripts for data filtering';
