-- Blog demo v2: fictional data only; empty volume initialization only.
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE TABLE tb_user (
  id BIGINT NOT NULL COMMENT '用户编号',
  username VARCHAR(64) NOT NULL COMMENT '登录名',
  password VARCHAR(255) NOT NULL COMMENT '虚构不可登录密码占位',
  nickname VARCHAR(64) NULL COMMENT '昵称',
  email VARCHAR(128) NULL COMMENT '邮箱',
  avatar VARCHAR(255) NULL COMMENT '头像地址',
  status TINYINT NOT NULL COMMENT '状态：1启用，0停用',
  create_time DATETIME NOT NULL COMMENT '创建时间',
  update_time DATETIME NOT NULL COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='博客用户';
CREATE TABLE tb_category (
  id BIGINT NOT NULL COMMENT '分类编号',
  name VARCHAR(64) NOT NULL COMMENT '分类名称',
  description VARCHAR(255) NULL COMMENT '分类说明',
  sort INT NOT NULL COMMENT '排序值',
  create_time DATETIME NOT NULL COMMENT '创建时间',
  update_time DATETIME NOT NULL COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_category_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='博客分类';
CREATE TABLE tb_tag (
  id BIGINT NOT NULL COMMENT '标签编号',
  name VARCHAR(64) NOT NULL COMMENT '标签名称',
  create_time DATETIME NOT NULL COMMENT '创建时间',
  update_time DATETIME NOT NULL COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_tag_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文章标签';
CREATE TABLE tb_blog_post (
  id BIGINT NOT NULL COMMENT '文章编号',
  title VARCHAR(200) NOT NULL COMMENT '文章标题',
  summary VARCHAR(500) NULL COMMENT '摘要',
  content LONGTEXT NOT NULL COMMENT '文章正文',
  cover_image VARCHAR(255) NULL COMMENT '封面地址',
  author_id BIGINT NOT NULL COMMENT '作者编号',
  category_id BIGINT NULL COMMENT '分类编号',
  status TINYINT NOT NULL COMMENT '状态：0草稿，1已发布，2归档',
  view_count INT UNSIGNED NOT NULL COMMENT '浏览量',
  create_time DATETIME NOT NULL COMMENT '创建时间',
  update_time DATETIME NOT NULL COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY ix_post_category_status (category_id,status),
  KEY ix_post_author (author_id),
  KEY ix_post_created (create_time),
  FOREIGN KEY (author_id) REFERENCES tb_user(id),
  FOREIGN KEY (category_id) REFERENCES tb_category(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='博客文章';
CREATE TABLE tb_post_tag (
  id BIGINT NOT NULL COMMENT '关联编号',
  post_id BIGINT NOT NULL COMMENT '文章编号',
  tag_id BIGINT NOT NULL COMMENT '标签编号',
  create_time DATETIME NOT NULL COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_post_tag (post_id,tag_id),
  KEY ix_post_tag_tag (tag_id),
  FOREIGN KEY (post_id) REFERENCES tb_blog_post(id),
  FOREIGN KEY (tag_id) REFERENCES tb_tag(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文章标签多对多关联';
CREATE TABLE ai_conversation (
  id BIGINT NOT NULL COMMENT '会话编号',
  user_id BIGINT NOT NULL COMMENT '用户编号',
  name VARCHAR(200) NOT NULL COMMENT '会话标题',
  icon VARCHAR(100) NULL COMMENT '图标',
  status TINYINT NOT NULL COMMENT '状态：1活跃，0关闭',
  create_time DATETIME NOT NULL COMMENT '创建时间',
  update_time DATETIME NOT NULL COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY ix_conversation_user (user_id),
  FOREIGN KEY (user_id) REFERENCES tb_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI会话';
CREATE TABLE ai_chat_messages (
  message_id BIGINT NOT NULL COMMENT '消息编号',
  content LONGTEXT NULL COMMENT '消息正文',
  reasoning_content LONGTEXT NULL COMMENT '推理内容',
  message_type VARCHAR(32) NOT NULL COMMENT '消息类型：text或summary',
  role VARCHAR(16) NOT NULL COMMENT '角色：user或assistant',
  parent_message_id BIGINT NULL COMMENT '父消息编号',
  conversation_id BIGINT NOT NULL COMMENT '所属会话编号',
  user_id BIGINT NOT NULL COMMENT '消息用户编号',
  token_count INT UNSIGNED NOT NULL COMMENT 'Token数量',
  source VARCHAR(32) NOT NULL COMMENT '来源：chat或search',
  status TINYINT NOT NULL COMMENT '状态：1完成，0中断',
  version INT NOT NULL COMMENT '消息版本',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  updated_at DATETIME NOT NULL COMMENT '更新时间',
  PRIMARY KEY (message_id),
  KEY ix_message_conversation_created (conversation_id,created_at),
  KEY ix_message_user (user_id),
  FOREIGN KEY (parent_message_id) REFERENCES ai_chat_messages(message_id),
  FOREIGN KEY (conversation_id) REFERENCES ai_conversation(id),
  FOREIGN KEY (user_id) REFERENCES tb_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI聊天消息';
CREATE TABLE ai_doc_search (
  id BIGINT NOT NULL COMMENT '搜索编号',
  conversation_id BIGINT NOT NULL COMMENT '会话编号',
  message_id BIGINT NOT NULL COMMENT '关联消息编号',
  query VARCHAR(500) NOT NULL COMMENT '检索词',
  search_result JSON NULL COMMENT '检索结果',
  result_count INT UNSIGNED NOT NULL COMMENT '命中数量',
  status TINYINT NOT NULL COMMENT '状态：1成功，0失败',
  create_time DATETIME NOT NULL COMMENT '创建时间',
  update_time DATETIME NOT NULL COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY ix_doc_conversation (conversation_id),
  FOREIGN KEY (conversation_id) REFERENCES ai_conversation(id),
  FOREIGN KEY (message_id) REFERENCES ai_chat_messages(message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档搜索记录';
CREATE TABLE ai_web_search (
  id BIGINT NOT NULL COMMENT '搜索编号',
  conversation_id BIGINT NOT NULL COMMENT '会话编号',
  message_id BIGINT NOT NULL COMMENT '关联消息编号',
  query VARCHAR(500) NOT NULL COMMENT '检索词',
  search_result JSON NULL COMMENT '检索结果',
  provider VARCHAR(32) NOT NULL COMMENT '虚构搜索提供者',
  status TINYINT NOT NULL COMMENT '状态：1成功，0失败',
  create_time DATETIME NOT NULL COMMENT '创建时间',
  update_time DATETIME NOT NULL COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY ix_web_conversation (conversation_id),
  FOREIGN KEY (conversation_id) REFERENCES ai_conversation(id),
  FOREIGN KEY (message_id) REFERENCES ai_chat_messages(message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='网页搜索记录';
CREATE TABLE tb_consultation (
  id BIGINT NOT NULL COMMENT '咨询编号',
  user_id BIGINT NULL COMMENT '用户编号，匿名允许空',
  email VARCHAR(128) NOT NULL COMMENT '联系邮箱',
  type VARCHAR(32) NOT NULL COMMENT '咨询类型：question或feedback',
  content TEXT NOT NULL COMMENT '咨询正文',
  content_type VARCHAR(32) NOT NULL COMMENT '正文格式：text或markdown',
  reply_status TINYINT NOT NULL COMMENT '回复状态：0未回复，1已回复',
  reply_content TEXT NULL COMMENT '回复正文',
  reply_content_type VARCHAR(32) NULL COMMENT '回复格式',
  create_time DATETIME NOT NULL COMMENT '创建时间',
  reply_time DATETIME NULL COMMENT '回复时间',
  update_time DATETIME NOT NULL COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY ix_consultation_reply (reply_status,create_time),
  KEY ix_consultation_user (user_id),
  FOREIGN KEY (user_id) REFERENCES tb_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户咨询';
