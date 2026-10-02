// landing 命名空间：落地页所有面向用户的文案（简体中文，作为翻译基准）
export default {
  meta: {
    title: 'DB-Genius | 开源 AI 数据库管理大师 - 自然语言生成 SQL · 智能工作流 · 数据库对比分析',
    description:
      'DB-Genius 是开源的 AI 数据库管理平台：用自然语言生成并执行 SQL、上传 Excel 自动完成批量数据工作流、对比不同环境数据库差异并生成安全的发版脚本。支持 MySQL、PostgreSQL、MongoDB、Oracle、SQL Server、MariaDB、TiDB、OceanBase、Doris、StarRocks 十种主流数据库，不同类型之间可相互对比。开源自部署，数据完全私有。',
    keywords:
      '开源数据库工具,AI 数据库,自然语言转 SQL,AI SQL 生成,Chat2SQL,Text-to-SQL,MySQL,PostgreSQL,MongoDB,Oracle,SQL Server,MariaDB,TiDB,OceanBase,Doris,StarRocks,跨数据库对比,发版 SQL,Excel 批量导入,数据库自动化,DB-Genius,AI 数据库大师',
    ogTitle: 'DB-Genius | 开源 AI 数据库管理大师',
    ogDescription:
      '开源的 AI 数据库管理平台：自然语言生成 SQL、智能工作流自动化、数据库对比分析。支持 10 种主流数据库，开源自部署，数据完全私有。',
    ogImageAlt: 'DB-Genius 开源 AI 数据库管理平台产品界面',
    ogLocale: 'zh_CN',
  },
  nav: {
    mainNav: '主导航',
    features: '核心功能',
    databases: '支持数据库',
    showcase: '产品展示',
    howItWorks: '工作流程',
    faq: '常见问题',
    login: '登录系统',
    freeTrial: '免费体验',
    tryOpenSource: '体验开源版',
    openMenu: '打开菜单',
  },
  hero: {
    ariaLabel: '产品介绍',
    tag: 'AI 驱动 · 开源免费',
    titleLine1: 'AI 数据库管理大师',
    titleLine2: '一句话搞定 SQL',
    desc: 'DB-Genius 是开源的 AI 数据库管理平台：自然语言生成并执行 SQL、Excel 智能工作流自动化、数据库对比分析。支持 10 种主流数据库，让数据操作更智能、更高效、更安全。',
    cta: '开始在线体验',
    trust1: '开源免费，代码透明可审计',
    trust2: '支持自部署，数据完全私有',
    trust3: '执行过程透明可追踪',
    screenshotAlt: 'DB-Genius AI 对话界面：用自然语言查询博客数据库，AI 自动生成 SQL 并以表格返回查询结果',
    float1: '自然语言 → SQL',
    float2: '高危操作自动警告',
  },
  features: {
    title: '核心功能',
    subtitle: '三大核心能力，覆盖数据库管理全场景',
    items: {
      sql: {
        title: '智能 SQL 生成',
        desc: '用自然语言描述需求，AI 自动生成精准 SQL 语句并实时执行，结果即时反馈。支持复杂查询、多表关联。',
      },
      workflow: {
        title: '工作流自动化',
        desc: '上传 Excel 文件，AI 自动解析数据、生成批量 SQL、执行并验证。多步骤任务全自动完成，每步透明可追踪。',
      },
      compare: {
        title: '数据库对比分析',
        desc: '对比生产与测试环境数据库差异，不同类型数据库之间也能相互对比结构与数据。自动生成发版 SQL 脚本，包含 DDL 变更、高危操作警告，确保发布安全。',
      },
    },
  },
  databases: {
    ariaLabel: '支持的数据库',
    title: '支持主流数据库',
    subtitle: '关系型、文档型、分布式与 OLAP 分析型数据库全覆盖，不同类型之间可相互对比结构与数据',
    logoAlt: '{name} 数据库 Logo',
    types: {
      relational: '关系型',
      document: '文档型',
      distributedHtap: '分布式 HTAP',
      distributed: '分布式',
      olap: 'OLAP 分析',
    },
  },
  showcase: {
    ariaLabel: '产品功能展示',
    title: '产品展示',
    subtitle: '真实界面，真实能力 —— 所见即所得',
    items: {
      sql: {
        tab: '自然语言查数据',
        title: '说一句话，SQL 自动生成并执行',
        desc: '用中文描述你的查询需求，AI 自动识别意图、生成精准 SQL、实时执行并以表格返回结果。支持复杂查询与多表关联，每一步流式展示、透明可追踪。',
        alt: 'DB-Genius 自然语言查询：AI 自动生成 SQL 并返回文章列表查询结果表格',
      },
      intent: {
        tab: '透明执行过程',
        title: 'AI 的每一步思考，你都看得见',
        desc: '意图识别、智能体路由、SQL 执行、结果总结——完整的推理与执行链路实时流式呈现，可随时查看中间结果，让 AI 操作不再黑盒。',
        alt: 'DB-Genius AI 意图识别结果与智能体路由执行过程实时流式展示',
      },
      compare: {
        tab: '环境对比发版',
        title: '生产 vs 测试，差异一目了然',
        desc: '覆盖关系型、文档型、分布式与 OLAP 等 10 种主流数据库，不同类型之间也能相互对比结构与数据差异。AI 自动生成发版 SQL 脚本，并对 DDL 变更与高危操作给出警告，让每次发布都安全可靠。',
        alt: 'DB-Genius 数据库对比功能：选择 Pre 与 Test 数据库进行差异分析',
      },
      config: {
        tab: '连接即文档',
        title: '添加连接，自动生成结构文档',
        desc: '填入数据库连接信息（支持 MySQL、PostgreSQL、Oracle、MongoDB 等 10 种主流数据库），系统自动验证连通性并生成数据库结构文档，AI 借此理解你的表结构，生成更贴合业务的 SQL。',
        alt: 'DB-Genius 数据库配置页面：MySQL 连接管理与连通性验证',
      },
    },
  },
  howItWorks: {
    title: '工作流程',
    subtitle: '简单三步，开启智能数据库管理之旅',
    steps: {
      step1: {
        title: '配置数据库',
        desc: '添加数据库连接信息，支持 MySQL、Oracle、MongoDB 等 10 种主流数据库，自动验证连通性并生成结构文档',
      },
      step2: {
        title: '对话式交互',
        desc: '用自然语言描述需求，AI 自动分析意图、生成 SQL、执行并返回结果',
      },
      step3: {
        title: '获取结果',
        desc: '实时流式展示每一步执行过程，最终呈现完整的数据分析结果',
      },
    },
  },
  faq: {
    ariaLabel: '常见问题',
    title: '常见问题',
    subtitle: '关于 DB-Genius，你可能想了解这些',
    items: {
      free: {
        q: 'DB-Genius 是开源免费的吗？',
        a: '是的。DB-Genius 是开源项目，可以免费获取源码并自行部署使用，也可以直接在官网体验在线演示。开源意味着代码透明可审计，部署在自己的环境中，数据完全由你掌控。',
      },
      databases: {
        q: '支持哪些数据库？',
        a: '目前支持 MySQL、PostgreSQL、MongoDB、Oracle、SQL Server、MariaDB、TiDB、OceanBase、Doris、StarRocks 十种主流数据库，覆盖关系型、文档型、分布式与 OLAP 分析型场景；不同类型的数据库之间也可以相互对比结构或数据差异。添加连接后系统会自动验证连通性并生成结构文档。',
      },
      client: {
        q: '需要下载安装客户端吗？',
        a: '不需要。DB-Genius 是 B/S 架构的网页应用，部署完成后打开浏览器即可使用，无需安装任何客户端，也不占用本地资源。',
      },
      safety: {
        q: 'AI 生成的 SQL 安全吗？会不会误删数据？',
        a: 'AI 的每一步执行过程都会流式展示、透明可追踪；在数据库对比与发版场景中，系统会自动识别 DDL 变更与高危操作并给出警告，帮助你在执行前确认风险。',
      },
      security: {
        q: '我的数据库连接信息安全吗？',
        a: '数据库连接信息仅用于你发起的查询与任务，系统会在添加连接时验证连通性并生成结构文档。DB-Genius 开源自部署，所有数据与连接信息都保存在你自己的环境中，代码透明可审计。',
      },
      contribute: {
        q: '如何为项目贡献？',
        a: '欢迎通过 GitHub 仓库提交 Issue 与 Pull Request 参与共建。',
      },
    },
  },
  cta: {
    ariaLabel: '立即开始',
    title: '现在开始，让 AI 帮你管理数据库',
    subtitle: '开源免费 · 支持自部署 · 数据完全私有',
    button: '开始在线体验',
  },
  footer: {
    brandDesc: 'AI 驱动的数据库管理平台，让数据操作更智能、更高效、更安全。',
    product: '产品',
    support: '支持',
    productNav: '产品导航',
    supportNav: '支持导航',
    features: '核心功能',
    showcase: '产品展示',
    howItWorks: '工作流程',
    faq: '常见问题',
    login: '登录系统',
    tagline: 'AI 驱动的数据库管理平台。',
  },
}
