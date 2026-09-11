CREATE TABLE IF NOT EXISTS sample_table (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO sample_table (name) VALUES ('Example 1'), ('Example 2');
