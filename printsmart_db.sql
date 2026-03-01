-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Mar 01, 2026 at 06:13 PM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `printsmart_db`
--

-- --------------------------------------------------------

--
-- Table structure for table `cart`
--
CREATE TABLE `cart` (
  `cart_id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `product_id` int(11) NOT NULL,
  `quantity` int(11) DEFAULT 1,
  `total_price` decimal(10,2) DEFAULT NULL,
  `item_details` text DEFAULT NULL,
  `file_path` text DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`cart_id`),
  KEY `user_id` (`user_id`),
  KEY `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=24 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `categories`
--
CREATE TABLE `categories` (
  `category_id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) NOT NULL,
  `slug` varchar(50) NOT NULL,
  `icon_path` varchar(255) DEFAULT NULL,
  `description` text DEFAULT NULL,
  `image_path` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`category_id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `categories`
--
INSERT INTO `categories` (`category_id`, `name`, `slug`, `icon_path`, `description`, `image_path`) VALUES
(1, 'Large Format & Signage', 'signage', 'images/icon-signage.png', NULL, NULL),
(2, 'Sticker Labels', 'stickers', 'images/icon-sticker.png', NULL, NULL),
(3, 'Document & Photo Printing', 'documents', 'images/icon-doc.png', NULL, NULL),
(4, 'Apparel', 'apparel', 'images/icon-shirt.png', NULL, NULL);

-- --------------------------------------------------------

--
-- Table structure for table `orders`
--
CREATE TABLE `orders` (
  `order_id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `total_amount` decimal(10,2) NOT NULL,
  `payment_method` varchar(50) DEFAULT NULL,
  `payment_status` enum('pending','paid','failed') DEFAULT 'pending',
  `order_status` enum('pending','processing','ready_for_pickup','completed','cancelled') DEFAULT 'pending',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`order_id`),
  KEY `user_id` (`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `orders`
--
INSERT INTO `orders` (`order_id`, `user_id`, `total_amount`, `payment_method`, `payment_status`, `order_status`, `created_at`) VALUES
(1, 1, 1094.00, 'GCash', 'paid', 'pending', '2025-12-19 09:42:30'),
(2, 1, 1094.00, 'Credit Card', 'paid', 'processing', '2026-01-04 13:05:01'),
(3, 1, 350.00, 'GCash', 'paid', 'pending', '2026-01-05 13:18:24'),
(4, 1, 130.00, 'Credit Card', 'paid', 'pending', '2026-01-05 13:25:03'),
(5, 1, 350.00, 'GCash', 'paid', 'pending', '2026-01-05 13:28:24'),
(6, 1, 350.00, 'Credit Card', 'paid', 'pending', '2026-01-05 13:33:19'),
(7, 1, 100.00, 'Credit Card', 'paid', 'pending', '2026-01-05 13:36:50'),
(8, 1, 150.00, 'Credit Card', 'paid', 'pending', '2026-01-05 13:39:09'),
(9, 1, 140.00, 'Credit Card', 'paid', 'pending', '2026-01-05 13:44:10'),
(10, 2, 350.00, 'Credit Card', 'paid', 'pending', '2026-01-05 14:07:01'),
(11, 4, 230.00, 'Credit Card', 'paid', 'processing', '2026-01-05 18:29:08'),
(12, 2, 1250.00, 'Credit Card', 'paid', 'pending', '2026-01-10 11:41:27'),
(13, 8, 275.00, 'Credit Card', 'paid', '', '2026-01-16 07:30:12');

-- --------------------------------------------------------

--
-- Table structure for table `order_items`
--
CREATE TABLE `order_items` (
  `item_id` int(11) NOT NULL AUTO_INCREMENT,
  `order_id` int(11) NOT NULL,
  `product_id` int(11) NOT NULL,
  `quantity` int(11) DEFAULT 1,
  `item_details` text DEFAULT NULL,
  `file_path` text DEFAULT NULL,
  `price_at_time` decimal(10,2) NOT NULL,
  `uploaded_file_path` varchar(255) DEFAULT NULL,
  `specifications` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`specifications`)),
  PRIMARY KEY (`item_id`),
  KEY `order_id` (`order_id`),
  KEY `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `order_items`
--
INSERT INTO `order_items` (`item_id`, `order_id`, `product_id`, `quantity`, `item_details`, `file_path`, `price_at_time`, `uploaded_file_path`, `specifications`) VALUES
(1, 5, 2, 1, 'Variant: 3mm - A3', 'uploads/cart_1_logo.png', 300.00, NULL, NULL),
(2, 6, 7, 2, 'Supply: T-Shirt - CVC Cotton - XS-Small | Color: Navy Blue', 'uploads/cart_1_basket.png', 300.00, NULL, NULL),
(3, 7, 2, 1, 'Variant: 3mm - 4R', 'uploads/cart_1_basket.png', 50.00, NULL, NULL),
(4, 8, 2, 2, 'Variant: 3mm - 4R', 'uploads/cart_1_logo.png', 100.00, NULL, NULL),
(5, 9, 1, 1, 'Material: Election Tarp | Size: 2.0x3.0 ft | NOTE: add eyelets', 'uploads/cart_1_logo.png', 90.00, NULL, NULL),
(6, 10, 1, 1, 'Material: Blackout Tarp | Size: 2.0x3.0 ft | NOTE: put some eyelets please', 'uploads/cart_2_logo.png', 300.00, NULL, NULL),
(7, 11, 1, 2, 'Material: Election Tarp | Size: 2.0x3.0 ft | NOTE: bukol sa ulo', 'uploads/cart_4_basket.png', 180.00, NULL, NULL),
(8, 12, 1, 4, 'Material: Blackout Tarp | Size: 2.0x3.0 ft | NOTE: test', 'uploads/cart_2_logo.png', 1200.00, NULL, NULL),
(9, 13, 1, 1, 'Material: Election Tarp | Size: 3.0x5.0 ft | NOTE: ADD EYELETS', 'uploads/cart_8_Screenshot_2026-01-13_at_1.57.49_PM.png', 225.00, NULL, NULL);

-- --------------------------------------------------------

--
-- Table structure for table `products`
--
CREATE TABLE `products` (
  `product_id` int(11) NOT NULL AUTO_INCREMENT,
  `category_id` int(11) NOT NULL,
  `name` varchar(100) NOT NULL,
  `description` text DEFAULT NULL,
  `base_price` decimal(10,2) NOT NULL,
  `image_path` varchar(255) DEFAULT NULL,
  `is_active` tinyint(1) DEFAULT 1,
  `stock` int(11) DEFAULT 100,
  PRIMARY KEY (`product_id`),
  KEY `category_id` (`category_id`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `products`
--
INSERT INTO `products` (`product_id`, `category_id`, `name`, `description`, `base_price`, `image_path`, `is_active`, `stock`) VALUES
(1, 1, 'Tarpaulin Printing', 'Durable tarpaulin prints for indoor and outdoor use', 20.00, 'uploads/product_1.png', 1, 100),
(2, 1, 'Sintra Board', 'Clean, rigid displays ideal for signage and standees', 0.00, NULL, 1, 100),
(3, 2, 'Sticker Labels', 'High-quality sticker labels for products and packaging', 0.00, NULL, 1, 100),
(4, 3, 'Document Printing', 'Professional document printing for everyday needs', 0.00, NULL, 1, 100),
(5, 3, 'Photo Printing', 'Sharp, vibrant photo prints in various sizes', 0.00, NULL, 1, 100),
(6, 3, 'ID Picture Packages', 'Fast and reliable ID photo packages (Rush ID)', 0.00, NULL, 1, 100),
(7, 4, 'Customized Shirts', 'Premium custom-printed apparel for any purpose', 0.00, NULL, 1, 100);

-- --------------------------------------------------------

--
-- Table structure for table `product_features`
--
CREATE TABLE `product_features` (
  `feature_id` int(11) NOT NULL AUTO_INCREMENT,
  `product_id` int(11) DEFAULT NULL,
  `feature_text` varchar(255) NOT NULL,
  PRIMARY KEY (`feature_id`),
  KEY `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=22 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `product_features`
--
INSERT INTO `product_features` (`feature_id`, `product_id`, `feature_text`) VALUES
(1, 1, 'Multiple material options'),
(2, 1, 'Custom sizes with automatic price calculation'),
(3, 1, 'Optional layout design support available'),
(4, 2, 'Available in 3mm and 5mm thickness'),
(5, 2, 'Standard or fully custom sizing'),
(6, 2, 'Optional back stand or box type add-on'),
(7, 3, 'Glossy or matte finish options'),
(8, 3, 'Sheet-based or custom size pricing'),
(9, 3, 'Optional pre-cut and label design service'),
(10, 4, 'Multiple paper sizes and color options'),
(11, 4, 'Clear, matrix-based pricing'),
(12, 4, 'Supports PDF and DOCX files'),
(13, 5, 'Wide range of photo sizes available'),
(14, 5, 'Accurate color reproduction'),
(15, 5, 'Optional layout assistance for photos'),
(16, 6, 'Multiple package options and sizes'),
(17, 6, 'Optional photo enhancement and outfit change'),
(18, 6, 'Softcopy add-on available'),
(19, 7, 'Multiple garment types and fabric choices'),
(20, 7, 'Supply & print or print-only options'),
(21, 7, 'Optional layout and placement assistance');

-- --------------------------------------------------------

--
-- Table structure for table `product_variants`
--
CREATE TABLE `product_variants` (
  `variant_id` int(11) NOT NULL AUTO_INCREMENT,
  `product_id` int(11) NOT NULL,
  `variant_name` varchar(100) NOT NULL,
  `price` decimal(10,2) NOT NULL,
  `stock_quantity` int(11) DEFAULT 100,
  PRIMARY KEY (`variant_id`),
  KEY `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=52 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `product_variants`
--
INSERT INTO `product_variants` (`variant_id`, `product_id`, `variant_name`, `price`, `stock_quantity`) VALUES
(1, 1, 'Election Tarp', 20.00, 100),
(2, 1, 'Ordinary Tarp', 25.00, 100),
(3, 1, 'Blackout Tarp', 50.00, 100),
(4, 5, '2R (Wallet Size)', 5.00, 1000),
(5, 5, '3R (3.5x5)', 6.00, 1000),
(6, 5, '4R (4x6)', 10.00, 1000),
(7, 5, '5R (5x7)', 15.00, 1000),
(8, 5, '8R (8x10)', 40.00, 1000),
(9, 5, 'A4 (8.3x11.7)', 60.00, 1000),
(10, 3, 'A4 Sheet', 100.00, 500),
(11, 3, 'A3 Sheet', 180.00, 500),
(12, 4, 'Short - Black & White', 6.00, 5000),
(13, 4, 'Short - Semi Color', 10.00, 5000),
(14, 4, 'Short - Full Color', 15.00, 5000),
(15, 4, 'A4 - Black & White', 6.00, 5000),
(16, 4, 'A4 - Semi Color', 11.00, 5000),
(17, 4, 'A4 - Full Color', 16.00, 5000),
(18, 4, 'Long - Black & White', 7.00, 5000),
(19, 4, 'Long - Semi Color', 12.00, 5000),
(20, 4, 'Long - Full Color', 17.00, 5000),
(21, 5, '2R (Wallet Size)', 4.00, 1000),
(22, 5, '3R (3.5x5)', 6.00, 1000),
(23, 5, '4R (4x6)', 10.00, 1000),
(24, 5, '5R (5x7)', 15.00, 1000),
(25, 5, '8R (8x10)', 40.00, 1000),
(26, 5, 'A4 (8.3x11.7)', 60.00, 1000),
(27, 6, 'Package A (8pcs 1x1)', 60.00, 1000),
(28, 6, 'Package B (6pcs 2x2)', 100.00, 1000),
(29, 6, 'Package C (8pcs Passport Size)', 100.00, 1000),
(30, 6, 'Package D (4pcs Passport, 3pcs 2x2)', 100.00, 1000),
(31, 6, 'Package E (6pcs 1x1, 5pcs 2x2)', 100.00, 1000),
(32, 6, 'Package F (Mixed Set)', 100.00, 1000),
(33, 7, 'Print Fee - Logo (5x5)', 60.00, 1000),
(34, 7, 'Print Fee - A4 Size', 100.00, 1000),
(35, 7, 'Print Fee - A3 Size', 200.00, 1000),
(36, 7, 'T-Shirt - CVC Cotton - XS-Small', 150.00, 100),
(37, 7, 'T-Shirt - CVC Cotton - Med-Large', 180.00, 100),
(38, 7, 'T-Shirt - CVC Cotton - XL-XXL', 200.00, 100),
(39, 7, 'T-Shirt - Drifit - Med-Large', 180.00, 100),
(40, 7, 'Polo Shirt - Honeycomb - Med-Large', 250.00, 100),
(41, 7, 'Long Sleeve - Cotton - Med-Large', 220.00, 100),
(42, 2, '3mm - 4R', 50.00, 1000),
(43, 2, '3mm - 5R', 70.00, 1000),
(44, 2, '3mm - A4', 150.00, 1000),
(45, 2, '3mm - A3', 300.00, 1000),
(46, 2, '5mm - 4R', 60.00, 1000),
(47, 2, '5mm - 5R', 80.00, 1000),
(48, 2, '5mm - A4', 180.00, 1000),
(49, 2, '5mm - A3', 360.00, 1000),
(50, 2, '3mm - Custom Rate', 5.00, 10000),
(51, 2, '5mm - Custom Rate', 10.00, 10000);

-- --------------------------------------------------------

--
-- Table structure for table `users`
--
CREATE TABLE `users` (
  `user_id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(50) DEFAULT NULL,
  `full_name` varchar(100) NOT NULL,
  `email` varchar(100) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `phone_number` varchar(20) DEFAULT NULL,
  `role` enum('customer','admin') DEFAULT 'customer',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `email` (`email`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `users`
--
INSERT INTO `users` (`user_id`, `username`, `full_name`, `email`, `password_hash`, `phone_number`, `role`, `created_at`) VALUES
(1, 'admin', 'System Administrator', 'admin@printsmart.com', 'scrypt:32768:8:1$taQJzWKPvoUVczVL$b83bf5511658ca2c23b7bebd96462175cb4d2764ed2232e336d078e88f1eb4ecdea314df10fb22d415c2de157abbebde82861df512fd0f654994ca0497af9e40', '09123456789', 'admin', '2025-12-19 08:17:43'),
(2, NULL, 'Test1', 'test1@test.com', 'scrypt:32768:8:1$cSrdHiEvADQ8rpos$e8be4869c0a784bb979156ba33d1fdbb55a93ecbb3b9264e661dbab0add4b746114ae5b6da6314960e97587ce0525451b90c9c22884b3a3396fc5fea4206a8a4', '09123456789', 'customer', '2026-01-05 10:23:23'),
(3, NULL, 'System Printsmart', 'system.printsmart@gmail.com', 'scrypt:32768:8:1$OrfzLRWlhpHQJteh$6d0c27a53abc0cb7312a2cbacc5c162aff63cf0787bc56ba23d4331724453ef31a08f1059da482d03925e3344fd5ac7e0d8414de5851ae673c3a0d2a44bf62a1', NULL, 'customer', '2026-01-05 12:05:02'),
(4, NULL, 'Ray Salcedo', 'missraeka17@gmail.com', 'scrypt:32768:8:1$m2YmUmC4dvAA6uvr$f02348997e1e20fda493b4dfbd743544058f29068a330e94a758ceefaa5a2ef5e050255bcc91672ad098363469c93d1bf916f300b24a5be10e14b7559027d30d', NULL, 'customer', '2026-01-05 12:39:38'),
(5, NULL, 'Test2', 'test2@test.com', 'scrypt:32768:8:1$rDonyQCZv7CbGnzD$355a8f8b66045f47a131167cdf1ff165ef0fea2b7ea0b9423d249e8cbbe0c7853be2e3ad42e68ddd9c0e441bc3eb4817c2bca0b048bf821dc627dc2550fd1eb7', '9123456789', 'customer', '2026-01-05 14:20:24'),
(6, NULL, 'Test1', 'marc@gmail.com', 'scrypt:32768:8:1$6xpT7A6WkjwFRjLH$050a2d9c00e159a4d37adde155f7de5586d8983b2f7fd5b47fc6347c24972411f5be6e172a5c5f27530b5c57832cf1001e4e66682ecf24fbaafce1c1cff773b3', '9123456', 'customer', '2026-01-10 11:07:38'),
(7, NULL, 'Test1', 'test3@test.com', 'scrypt:32768:8:1$q0koDntnwRvUrDyw$ab06ca18948f16f7c22193acd3bd5c59b5de8f4331d7e09bebc5a31ea0d21f670b1b36539e0fa7dec371a46ca6bc97a4d04c3b361da2faaa27f7c700b5c8bd20', '9123456789', 'customer', '2026-01-10 11:08:32'),
(8, NULL, 'Test3', 'test4@test.com', 'scrypt:32768:8:1$bBBxtq5QYzxhdKUX$54096c262f7088ab0a239636d341097557b76101d2f2004a0e5ab344c769aa41a7fb1dfcd35811f3210417b47bf9a38d7eecf35e77306f64ce5d835893cf8738', '9123456789', 'customer', '2026-01-16 07:27:47');

-- --------------------------------------------------------

--
-- Constraints for dumped tables
--

--
-- Constraints for table `cart`
--
ALTER TABLE `cart`
  ADD CONSTRAINT `cart_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `cart_ibfk_2` FOREIGN KEY (`product_id`) REFERENCES `products` (`product_id`);

--
-- Constraints for table `orders`
--
ALTER TABLE `orders`
  ADD CONSTRAINT `orders_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`);

--
-- Constraints for table `order_items`
--
ALTER TABLE `order_items`
  ADD CONSTRAINT `order_items_ibfk_1` FOREIGN KEY (`order_id`) REFERENCES `orders` (`order_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `order_items_ibfk_2` FOREIGN KEY (`product_id`) REFERENCES `products` (`product_id`);

--
-- Constraints for table `products`
--
ALTER TABLE `products`
  ADD CONSTRAINT `products_ibfk_1` FOREIGN KEY (`category_id`) REFERENCES `categories` (`category_id`) ON DELETE CASCADE;

--
-- Constraints for table `product_features`
--
ALTER TABLE `product_features`
  ADD CONSTRAINT `product_features_ibfk_1` FOREIGN KEY (`product_id`) REFERENCES `products` (`product_id`) ON DELETE CASCADE;

--
-- Constraints for table `product_variants`
--
ALTER TABLE `product_variants`
  ADD CONSTRAINT `product_variants_ibfk_1` FOREIGN KEY (`product_id`) REFERENCES `products` (`product_id`) ON DELETE CASCADE;

COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;