-- Fictional data only. Loaded once on the first initialization of the demo volume.
CREATE TABLE customers (
  id INT PRIMARY KEY,
  name VARCHAR(50) NOT NULL COMMENT '客户姓名',
  city VARCHAR(50) NOT NULL COMMENT '所在城市',
  registered_at DATE NOT NULL COMMENT '注册日期'
) COMMENT='客户信息';
CREATE TABLE products (
  id INT PRIMARY KEY,
  name VARCHAR(80) NOT NULL COMMENT '商品名称',
  category VARCHAR(40) NOT NULL COMMENT '商品分类',
  price DECIMAL(10,2) NOT NULL COMMENT '当前单价'
) COMMENT='商品目录';
CREATE TABLE orders (
  id INT PRIMARY KEY,
  customer_id INT NOT NULL,
  order_date DATE NOT NULL COMMENT '下单日期',
  status VARCHAR(20) NOT NULL COMMENT 'paid/shipped/completed/cancelled',
  total_amount DECIMAL(10,2) NOT NULL COMMENT '订单总金额',
  FOREIGN KEY (customer_id) REFERENCES customers(id)
) COMMENT='订单';
CREATE TABLE order_items (
  id INT PRIMARY KEY,
  order_id INT NOT NULL,
  product_id INT NOT NULL,
  quantity INT NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL COMMENT '成交单价',
  FOREIGN KEY (order_id) REFERENCES orders(id),
  FOREIGN KEY (product_id) REFERENCES products(id)
) COMMENT='订单明细';

INSERT INTO customers VALUES
(1,'张晓','杭州','2025-01-03'),(2,'李明','上海','2025-01-10'),
(3,'王芳','北京','2025-02-01'),(4,'赵宇','杭州','2025-02-14'),
(5,'陈静','广州','2025-03-01'),(6,'刘洋','成都','2025-03-05');
INSERT INTO products VALUES
(1,'无线鼠标','办公',99.00),(2,'机械键盘','办公',299.00),
(3,'保温杯','生活',79.00),(4,'台灯','生活',129.00),
(5,'蓝牙耳机','数码',199.00),(6,'充电宝','数码',149.00);
INSERT INTO orders VALUES
(1,1,'2025-04-02','completed',398.00),
(2,2,'2025-04-05','completed',158.00),
(3,3,'2025-04-12','shipped',199.00),
(4,1,'2025-05-01','completed',278.00),
(5,4,'2025-05-06','paid',299.00),
(6,5,'2025-05-10','cancelled',99.00),
(7,6,'2025-06-01','completed',298.00),
(8,2,'2025-06-08','completed',328.00),
(9,4,'2025-06-15','shipped',258.00),
(10,3,'2025-06-20','paid',477.00);
INSERT INTO order_items VALUES
(1,1,1,1,99.00),(2,1,2,1,299.00),(3,2,3,2,79.00),
(4,3,5,1,199.00),(5,4,4,1,129.00),(6,4,6,1,149.00),
(7,5,2,1,299.00),(8,6,1,1,99.00),(9,7,6,2,149.00),
(10,8,4,1,129.00),(11,8,5,1,199.00),(12,9,4,2,129.00),
(13,10,2,1,299.00),(14,10,1,1,99.00),(15,10,3,1,79.00);
