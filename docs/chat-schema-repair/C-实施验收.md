# C：博客演示库与试用提示实施验收

## 最终状态

MySQL真实验收完成。A/B后端提交 `2ebca5d`，C应用/部署26文件提交 `01cc80e`；验收工具已提交a001f7e，文档由主代理随后本地提交。本次仅MySQL，不重跑其他九类数据库，不向生产发布。

十表为ai_conversation、ai_chat_messages、ai_doc_search、ai_web_search、tb_blog_post、tb_category、tb_tag、tb_post_tag、tb_user、tb_consultation；85字段，45行虚构数据。demo.sql定义明确类型、PK/FK/index和中文注释，seed.sql覆盖多用户、多对多标签、日期、状态、NULL、无搜索会话与未回复咨询。oracle.json包含五条独立只读SQL和种子确定预期。

根与生产Compose使用trial_mysql_blog_v2_data新逻辑卷，旧卷不挂载、不删除。root服务仅trial-demo profile开启，backend别名sqlchat-demo-mysql，无宿主端口。服务端、初始化客户端和查询客户端utf8mb4。健康检查覆盖十表及关键种子，全部init/schema/seed/health资产已纳入服务器检查与CI传输。

builtin仅连接目标变化时同步，密码解密比较后仅变化重新加密，递增验证版本、失效旧文档与错误；旧版本任务不可覆盖，新目标相同不刷新，自建config不修改。七语言试用/未知状态采用博客placeholder，正式模式保留原文。

## 验证结果

| 检查 | 结果 |
|---|---|
| 前端typecheck/build | 通过；既有Vite loader与大chunk警告 |
| s07+s13联合页面测试 | 2通过；主代理也独立复跑通过 |
| backend test_trial.py | 8通过；主代理复跑通过 |
| deploy test_trial_*.py | 21通过；主代理复跑通过 |
| Ruff、脚本py_compile、浏览器node --check、diff检查 | 通过 |
| 主代理后端组合/补跑 | 147项组合、34项补跑通过；app Ruff/mypy通过 |
| MySQL主栈 | 十表85列中文注释与5项SQL oracle通过，只读权限通过 |
| 独立空卷cold-init/restart | 两次oracle通过、healthy、OOM=false，随后主代理stop保留卷 |
| 三轮deepseek-flash | 语义答案、done/无error、summary/history、reasoning replay顺序均通过 |
| browser-only真实回放 | C运行通过，主代理独立复跑exit0；零chat POST |

AGENTS已检查。未改变核心业务边界或核心目录结构，保持不变。子代理未启动容器或重复调用真实模型；主代理串行运行Docker与模型，C仅按授权执行browser-only诊断。

## 实际恢复与冷初始化

首次真实启动暴露CRLF使pipefail参数失效；本次四个shell写为实际LF，.gitattributes强制*.sh text eol=lf。主代理按精确受控新容器恢复空库，未drop或删卷。临时硬编码CID恢复脚本位于.git/acceptance/chat-schema-repair，不作为产品代码提交。

独立cold-init又发现Windows bind mount执行位使官方entrypoint直接执行10-demo.sh，子进程缺docker_process_sql。init现支持直接执行与source：已有helper沿用；缺helper时仅source官方函数环境，官方source guard不会运行main，mysql_get_config取得socket。两个bash模拟测试通过，随后主代理新建sqlchat-blog-init-final实际冷启动成功。

该独立容器精确ID d0067b0fbfd1b39fa71cd70035a91876245eb45a7f9620113d1da070c1db3643：healthy、OOM=false，首次和restart均10表85列/5oracle通过，未重复种子；已stop，保留卷。此前失败init-check也已由主代理stop，保留卷。

主栈builtin id2现sqlchat_blog_demo、status1、version2、文档6676字符；自建id1未改，后续不选旧演示连接。MySQL SHOW GRANTS仅USAGE和本库SELECT/SHOW VIEW，中文HEX正确。

## 三轮模型与reasoning

既有deepseek-flash会话11/12/13均通过。推理字符1120/1512/540；最终summary与历史一致，SSE reasoning聚合内容/step及step-reasoning完整顺序匹配，reasoningContent字段无重复。报告只存字符数、块数、布尔值及最终用户正文，不保存推理正文、token、key或提供商payload。

公开SSE/history无modelCallId；脚本依据三条SQL流程的step/工具边界还原可见调用块，summary_delta交错不拆块。不宣称任意同step且无工具分隔的内部调用编号已验证。零推理提供商允许零块，不伪造。

主代理逐表核对10表85字段、nullable、PK、comment匹配实际schema。INTEGER为原适配器归一类型，本次未扩大unsigned输出要求。分类已发布数量3/1/1/0；热门文章标题/浏览量1200/850/650匹配独立SQL预期。脚本协议passed不自动等价语义正确，语义由主代理上述对照确认。

## 浏览器与安全工件

实际DOM确认Arco row-key为Vue键、没有data-row-key属性，并存在隐藏mobile-drawer与历史drawer。脚本根据API精确会话ID解析分页顺序并核验标题，历史drawer限定非mobile-drawer，等待对应messages响应与摘要正文。

browser-only复用11/12/13，不调用模型。三轮历史截图完成；继续会话11只回放，验证10张Markdown字段表、reasoning-card和中文字段，chat POST计数0。C与主代理独立执行均exit0。

```powershell
backend/.venv/Scripts/python.exe deploy/trial-mysql/verify-real-chat.py --browser-only --report .git/acceptance/chat-schema-repair/real-chat.json --screenshots .git/acceptance/chat-schema-repair/screenshots
```

本机安全工件：.git/acceptance/chat-schema-repair/mysql-oracle.json、real-chat.json、screenshots/trial-placeholder.png、history-1.png、history-2.png、history-3.png、chat-replay-11.png。失败截图仅诊断，不列为成功证据。全部.git工件不提交。汇总见主代理验收.md。
