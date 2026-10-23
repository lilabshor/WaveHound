-- Skema Relasional WaveHound (Mendukung MySQL 8.0 & SQLite)
-- Aturan Mutlak: Tidak ada kolom untuk menyimpan alamat MAC / RPA mentah di database.

CREATE TABLE IF NOT EXISTS sites (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id VARCHAR(64) PRIMARY KEY,
    site_id VARCHAR(64) NOT NULL,
    x DOUBLE NOT NULL,
    y DOUBLE NOT NULL,
    z DOUBLE NOT NULL,
    floor INT NOT NULL,
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    last_seen_at VARCHAR(32),
    created_at VARCHAR(32) NOT NULL,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

CREATE INDEX idx_nodes_site ON nodes(site_id);

CREATE TABLE IF NOT EXISTS devices_enrolled (
    id VARCHAR(64) PRIMARY KEY,
    site_id VARCHAR(64) NOT NULL,
    label VARCHAR(255) NOT NULL,
    owner_ref VARCHAR(255) NOT NULL,
    identity_type VARCHAR(32) NOT NULL,
    identity_secret TEXT NOT NULL,
    enrolled_at VARCHAR(32) NOT NULL,
    enrolled_by VARCHAR(64) NOT NULL,
    consent_ref VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    UNIQUE (site_id, label),
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tickets (
    id VARCHAR(64) PRIMARY KEY,
    site_id VARCHAR(64) NOT NULL,
    device_id VARCHAR(64) NOT NULL,
    opened_by VARCHAR(64) NOT NULL,
    opened_at VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    closed_at VARCHAR(32),
    note TEXT,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices_enrolled(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS readings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    site_id VARCHAR(64) NOT NULL,
    node_id VARCHAR(64) NOT NULL,
    device_id VARCHAR(64),
    seen_at VARCHAR(32) NOT NULL,
    received_at VARCHAR(32) NOT NULL,
    rssi INT NOT NULL,
    rssi_smooth DOUBLE,
    distance_m DOUBLE,
    channel INT,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices_enrolled(id) ON DELETE SET NULL
);

CREATE INDEX idx_readings_device_time ON readings(device_id, seen_at);
CREATE INDEX idx_readings_node_time ON readings(node_id, seen_at);

CREATE TABLE IF NOT EXISTS positions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    site_id VARCHAR(64) NOT NULL,
    device_id VARCHAR(64) NOT NULL,
    ticket_id VARCHAR(64) NOT NULL,
    estimated_at VARCHAR(32) NOT NULL,
    x DOUBLE NOT NULL,
    y DOUBLE NOT NULL,
    floor INT NOT NULL,
    confidence VARCHAR(32) NOT NULL,
    residual DOUBLE NOT NULL,
    node_count INT NOT NULL,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices_enrolled(id) ON DELETE CASCADE,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
);

CREATE INDEX idx_positions_device_time ON positions(device_id, estimated_at);

CREATE TABLE IF NOT EXISTS alerts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    site_id VARCHAR(64) NOT NULL,
    kind VARCHAR(64) NOT NULL,
    ref_id VARCHAR(64),
    created_at VARCHAR(32) NOT NULL,
    acked_by VARCHAR(64),
    acked_at VARCHAR(32),
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    username VARCHAR(128) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS roles (
    user_id VARCHAR(64) NOT NULL,
    site_id VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL,
    PRIMARY KEY (user_id, site_id, role),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    at VARCHAR(32) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    target_ref VARCHAR(128),
    detail TEXT,
    prev_hash VARCHAR(64) NOT NULL,
    entry_hash VARCHAR(64) NOT NULL
);

CREATE INDEX idx_audit_actor_time ON audit_log(actor_id, at);
