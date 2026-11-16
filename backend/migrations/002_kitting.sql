-- 联合备料方案：草案/生效/取消状态机、作业占用与用包登记
-- 新部署由 ORM 自动建表；已有库执行本文件补齐结构。

ALTER TABLE `jobs` ADD COLUMN `revision` int NOT NULL DEFAULT 1;
ALTER TABLE `kits` ADD COLUMN `revision` int NOT NULL DEFAULT 1;

CREATE TABLE `kitting_plans` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) DEFAULT NULL,
  `state` varchar(20) DEFAULT 'draft',
  `carry_limit` int DEFAULT NULL,
  `basis` json DEFAULT NULL,
  `fingerprint` varchar(64) DEFAULT NULL,
  `result` json DEFAULT NULL,
  `confirm_key` varchar(64) DEFAULT NULL,
  `cancel_key` varchar(64) DEFAULT NULL,
  `version` int NOT NULL DEFAULT 1,
  `created_by` varchar(100) DEFAULT NULL,
  `created_at` varchar(40) DEFAULT NULL,
  `activated_at` varchar(40) DEFAULT NULL,
  `cancelled_at` varchar(40) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `kitting_occupancy` (
  `id` int NOT NULL AUTO_INCREMENT,
  `plan_id` int DEFAULT NULL,
  `job_id` int NOT NULL,
  `created_at` varchar(40) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `job_id` (`job_id`),
  CONSTRAINT `kitting_occupancy_ibfk_1` FOREIGN KEY (`plan_id`) REFERENCES `kitting_plans` (`id`),
  CONSTRAINT `kitting_occupancy_ibfk_2` FOREIGN KEY (`job_id`) REFERENCES `jobs` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `kitting_plan_kits` (
  `id` int NOT NULL AUTO_INCREMENT,
  `plan_id` int DEFAULT NULL,
  `kit_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `plan_id` (`plan_id`,`kit_id`),
  CONSTRAINT `kitting_plan_kits_ibfk_1` FOREIGN KEY (`plan_id`) REFERENCES `kitting_plans` (`id`),
  CONSTRAINT `kitting_plan_kits_ibfk_2` FOREIGN KEY (`kit_id`) REFERENCES `kits` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
