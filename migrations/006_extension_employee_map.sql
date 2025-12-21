-- Migration: Create extension_employee_map table
-- Date: 2025-12-21
-- Purpose: Map extension numbers to employee names, learning from historical data

CREATE TABLE IF NOT EXISTS extension_employee_map (
    id SERIAL PRIMARY KEY,
    extension_number TEXT NOT NULL,
    employee_name TEXT NOT NULL,
    occurrence_count INTEGER DEFAULT 1,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    confidence_score REAL DEFAULT 0.5,
    UNIQUE(extension_number, employee_name)
);

CREATE INDEX IF NOT EXISTS idx_ext_map_extension ON extension_employee_map(extension_number);
CREATE INDEX IF NOT EXISTS idx_ext_map_employee ON extension_employee_map(employee_name);

COMMENT ON TABLE extension_employee_map IS 'Maps extension numbers to employee names, learned from call history';
COMMENT ON COLUMN extension_employee_map.confidence_score IS 'Confidence based on occurrence count: 50+=0.95, 20+=0.85, 10+=0.75, 5+=0.65, else 0.5';
