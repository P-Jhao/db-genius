# S14 trace 有界真实调度修订

本候选只交付三项测试/诊断源码：test_s14_runtime_tracing.py、test_s14_runtime_trace_schedule.py、s14_runtime_trace_diagnostics.py。support、metrics、accepted target/relay fixtures 在候选内仅作为原字节静态引用，不属于 overlay payload。业务源码、依赖、Compose、test_deploy_*、镜像、容器、目标与 receiver 未修改。原 13 文件运行候选和 6 文件诊断候选保持冻结。

## 已确认因果

root trace-live-02 返回 childExitCode1、completed=true、TimeoutError、原 tracing.py line248。实际条件是 same_channel_reset：每个本次 fr/ja worker exporter channel 必须看到本次旧版本回调的默认 en worker span，且新 span 的 start 晚于此前 localized span 的 end。

旧诊断中的 target_provision 是阶段回退错误：异常退出 with isolated_database 的第210行时，line trace 重新标记了该旧阶段，并被 makereport 再写入失败。line248 才是实际等待位置。到达该行意味着此前配置 status1、完整四span父子链、fr/ja、worker资源及精确 stale delta 已经过对应条件；这不是以 span 总数宣布通过。

root 保留的安全 protobuf 投影确认：最近 fr/ja 分别在 channel96/98，四个默认 en 回调全部在96，98没有en，原 required={96,98} 无法覆盖。旧代码每次用独立 docker exec 发布一个很快完成的 stale 回调，固定发 prefork×2 不保证每个已观察子进程都执行后续回调。当前证据支持调度覆盖不足；不据此认定生产 locale reset 已完成验收。root 失败回执与投影路径/SHA及数值证据写 root-failure-evidence.json，原文件不改。

## 调度与证明

保持 60 秒 deadline；预算从默认阶段开始，包含发布、指标与 snapshot 观察。deadline 到达后不发新批次、不返回通过，现有 I/O timeout 保持原实现。每批 2×实际 prefork 数，最多4批，总上限8×prefork（preflight限定1..16）。在单个容器 Python 进程内快速发布真实 apply_async 回调，减少逐次 docker exec 的间隔。没有 eager/mock、PID路由、睡眠任务、业务 monkeypatch 或降低断言。

发布脚本只查询本普通用户本次两个 fresh config，验证 owner/status1/version>0，再以 version-1 发布；headers 为新的 sampled traceparent 与原合成不可信标记，不带 locale。下一批必须等待上一批的精确 stale delta 和全部实际 worker trace ID 已观察到，同时仍缺 required channel。不能将数量或假定公平调度作为覆盖证明。

通过条件更严格：所有已发送默认回调都有自己的实际 worker span；其 locale=en、outcome=stale、resource固定为sqlchat-worker；精确累计 stale delta 等于总发布数；每个本次 localized channel 上都有同一 channel 的更晚默认 span。若同一 channel 承载多个 localized span，以其中最新 end 为界。required channel 不因连接断开而删除，其他 trace/channel 不补足缺口。达到60秒或4批仍缺覆盖就失败，不能仅增加timeout。

原两条 HTTP→publish→worker→schema parent chain、fr/ja资源、sample1/direct transport、trace_state/events、原始/编码合成header和已知credential absence 仍在原测试中执行。受保护 runner 固定 trace-only，要求 setup/call/teardown、无skip、trace通过报告与owner cleanup都成功；不重复 metrics。

trace_reset_progress.json 只原子写 bool/int/float：上限、已发布数/批数、精确指标delta、已验证自己的默认worker trace数量、要求/覆盖channel数量和完整性。它不是独立通过凭证；后续privacy或target/owner清理失败仍使整体失败。发生硬退出不能虚报清理。

诊断 runner 同时绑定新 trace/helper SHA 和原 support/metrics SHA。case 阶段只向前推进，异常出 with 不回退；helper 的失败固定归 same_channel_reset。源码位置与类型仍受保护，不输出原异常、locals、payload、headers或protobuf。进程隔离、私有child模式、DEVNULL和通过判定保留。

## root 下一次窗口

等待 root 明确完整组合再次 healthy，collector ready，sample1创建前注入，最终API/Worker digest分别正确，S15 PG目标可用，独占任务窗口。root 把本 manifest 的三个 backend/tests 文件 overlay 到独立完整组合 backend；本目录本身仅为patch/静态引用，不是完整应用，也不包含最终部署helper。保留 root/Luna 最终helper SHA与 root .env.s14 输入。

选择新的独立 SQLCHAT_S14_RUNTIME_REPORT_DIR，位于root .git/acceptance且在源码组合目录外。通过新runner执行，$rootBackendPath 为已叠入三个文件的最终组合 backend：

~~~powershell
& 'C:\Users\22126\Desktop\web\text2sql\sqlchat\backend\.venv\Scripts\python.exe' 'C:\Users\22126\Desktop\web\text2sql\sqlchat\.git\acceptance\s14-trace-scheduling-f59f6c8aa4f3434aa0cd863db957f136\backend\tests\s14_runtime_trace_diagnostics.py' --backend $rootBackendPath
~~~

入口只选择 test_real_http_worker_parent_chain_and_locale_reset。不要用旧234行runner，它钉原trace SHA。也不要直接pytest暴露原异常。生命周期/collector/秘密输入均由root负责，本子代理不开live窗口。

## 静态与合成验证

Ruff、strict mypy三源码通过，唯一 trace node collect1；强制live=0执行1skip，未inspect/API/DB/receiver操作。八个纯fake-clock/dispatch行为验证包括：第一批全落一channel、第二批补足后才通过；所有批仍偏一channel时到cap失败；其他trace不能补足覆盖；时间过早不能补足；坏locale失败；外来counter变化失败；丢失export只发第一批并到60秒失败；header准备超过预算时零发布即失败。额外合成with-unwind验证失败阶段保持same_channel_reset。进度JSON未出现合成header内容。

这些是控制流/上限和失败保护证明，不证明真实broker公平，也不是实际 trace runtime 通过。root 之后的受保护完整trace-only结果才是live证据。初次静态collect缺少accepted import-only参考文件，补齐原字节引用后通过；失败记录保留。AGENTS已检查，核心功能/目录不变，不修改。
