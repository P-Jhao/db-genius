#!/bin/bash
# Test every required table plus independent seed sentinels using the readonly account.
set -euo pipefail
export MYSQL_PWD="$TRIAL_PASSWORD"
result=$(mysql --default-character-set=utf8mb4 --protocol=TCP -h 127.0.0.1 -u "$TRIAL_USERNAME" -D "$TRIAL_DATABASE" -Nse "SELECT (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('ai_conversation','ai_chat_messages','ai_doc_search','ai_web_search','tb_blog_post','tb_category','tb_tag','tb_post_tag','tb_user','tb_consultation'))=10 AND (SELECT COUNT(*) FROM tb_blog_post)=8 AND (SELECT COUNT(*) FROM tb_category)=4 AND (SELECT COUNT(*) FROM tb_consultation WHERE reply_status=0 AND reply_time IS NULL)=2 AND (SELECT COUNT(*) FROM tb_blog_post WHERE id=1 AND title='MySQL 索引入门')=1")
[[ "$result" == 1 ]]
