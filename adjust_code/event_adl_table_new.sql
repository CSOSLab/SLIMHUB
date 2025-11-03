-- --------------------------------------------------------
-- 호스트:                          155.230.186.52
-- 서버 버전:                        10.6.22-MariaDB-0ubuntu0.22.04.1 - Ubuntu 22.04
-- 서버 OS:                        debian-linux-gnu
-- HeidiSQL 버전:                  11.3.0.6295
-- --------------------------------------------------------

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;


-- ad_raw 데이터베이스 구조 내보내기
CREATE DATABASE IF NOT EXISTS `adl_event` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci */;
USE `adl_event`;

-- 테이블 ad_raw.event_adl 구조 내보내기
CREATE TABLE IF NOT EXISTS `event_adl` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `house_mac` varchar(50) DEFAULT NULL,
  `location` varchar(255) DEFAULT NULL,
  `created_time` timestamp NULL DEFAULT NULL,
  `event_sequence` varchar(255) DEFAULT NULL,
  `adl` varchar(255) DEFAULT NULL,
  `truth_value` double DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `in_out` (
	`id` INT(10) NOT NULL AUTO_INCREMENT,
	`house_mac` VARCHAR(50) DEFAULT NULL,
	`location` VARCHAR(50) DEFAULT NULL,
	`created_time` TIMESTAMP NULL DEFAULT NULL,
	`direction` INT(10) NULL DEFAULT NULL,
	PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;


-- 테이블 데이터 ad_raw.event_adl:~0 rows (대략적) 내보내기
DELETE FROM `event_adl`;
/*!40000 ALTER TABLE `event_adl` DISABLE KEYS */;
/*!40000 ALTER TABLE `event_adl` ENABLE KEYS */;

/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IFNULL(@OLD_FOREIGN_KEY_CHECKS, 1) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40111 SET SQL_NOTES=IFNULL(@OLD_SQL_NOTES, 1) */;
