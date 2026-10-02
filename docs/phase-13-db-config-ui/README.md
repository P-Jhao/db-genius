# S13 数据库配置与试用版 UI 对齐

## 冻结边界

本候选以已验收 STOP 前端提交 `780becfd594016f093e015318d2c5c46bdc06072` 为 fresh base。父代理报告后续 `0b7df28` 只更新文档；本目录没有 `.git`，前端 `node_modules` 是共享依赖的 junction。S13 改动只在本副本验收，不包含后端、STOP 实现或 STOP 截图。

本次 40 个前端文件由既有 S13 草稿按文件白名单选择性叠加，包含试用状态门控、销售 FAQ 对齐、七种语言和数据库配置。完整文件路径及 SHA-256 见同目录 `freeze.json`。

## 数据库表单行为

- 新建仍默认 MySQL。用户主动选择十种类型之一时，端口改为对应默认值；编辑现有配置会载入服务端类型与原端口，不触发端口重置。未知服务端类型显示明确错误，不打开编辑窗或悄悄回退 MySQL。
- 默认端口为 MySQL 3306、PostgreSQL 5432、MongoDB 27017、MariaDB 3306、TiDB 4000、Doris 9030、StarRocks 9030、OceanBase 2881、Oracle 1521、SQL Server 1433。关系型适配器端口与当前后端适配器定义一致；MongoDB 27017 与现有后端配置测试夹具一致。端口默认是前端表单值，浏览器验收使用 mock API。
- MongoDB 认证字段必须同时填写或同时留空。编辑时清空两项会提交匿名配置；只填写一项会显示错误、保留弹窗和输入值且不发请求。编辑已有认证配置时，密码不会从服务端回填，重新提交认证需要成对输入用户名与密码。
- 关系型数据库新建需要用户名和密码。编辑时密码留空会按接口约定提交空字符串以保留已有密码；浏览器测试断言实际 PUT payload。
- Arco Modal 的 `@ok` 会在触发 `ok` 处理函数前关闭弹窗。表单改用 `@before-ok`，校验或 API 失败返回 `false` 并保留弹窗与数据，成功返回 `true` 后只关闭一次。回归测试覆盖校验失败后修正并成功、mock API 失败后用户重试成功，以及无自动重复 POST。

类型选项符合用户授权并已写入 `spec/01-产品需求文档.md` 4.1.1。此前 accepted UI 只有固定 MySQL 字段；S15/T01 截图差异应按新增类型选择能力解释，不将这项 UI 差异记为静态视觉完全相同。

## 试用与语言范围

试用状态加载失败时保持关闭写入入口并允许重试；处于试用版时聊天页隐藏上传和数据库对比，数据库、模型页隐藏受限管理操作。类型选择没有改变试用版权限。

落地页 FAQ 使用开源项目贡献说明，没有销售联系入口或销售文案。英文、简体中文、繁体中文、西班牙语、法语、日语、马来语均有密码提示、MongoDB 凭据配对/报错、关系型新建密码错误和未知数据库类型文案；测试在实际 locale 下用 `i18n.global.te` 检查每个 key 存在。

## 验收证据与限制

Playwright 测试使用本地 Vite 与浏览器路由 mock，输入与响应均为测试数据，不连真实后端；夹具明确设置 `VITE_API_BASE_URL=/api`，每次启动使用独立 Vite cacheDir。因此它验证页面交互、请求路径与 payload，不代表真实数据库连接或在线 API 已验收。

```powershell
node --test --test-concurrency=1 tests/s13-product-alignment.test.mjs tests/s13-trial-ui.test.mjs tests/s13-db-config-contract.test.mjs
pnpm --config.verify-deps-before-run=false typecheck
pnpm --config.verify-deps-before-run=false build
```

结果：浏览器 5/5 项通过；类型检查通过；生产构建通过。构建仍报告既有 Vite `__dirname` 配置迁移提示和超过 500 kB 的 bundle 提示，均不阻断构建。
