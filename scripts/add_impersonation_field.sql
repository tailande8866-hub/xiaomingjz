-- 添加冒充管理员检测字段
ALTER TABLE groups ADD COLUMN impersonation_detection_enabled BOOLEAN DEFAULT FALSE;
