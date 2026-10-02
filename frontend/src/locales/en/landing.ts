// landing namespace: all user-facing landing page copy (English)
export default {
  meta: {
    title: 'DB-Genius | Open-Source AI Database Management - Natural-Language SQL · Smart Workflows · Database Comparison',
    description:
      'DB-Genius is an open-source AI database management platform: generate and execute SQL from natural language, automate batch data workflows from Excel uploads, and compare databases across environments with safe release scripts. Supports ten major databases — MySQL, PostgreSQL, MongoDB, Oracle, SQL Server, MariaDB, TiDB, OceanBase, Doris, and StarRocks — with cross-type comparison. Open source and self-hosted: your data stays fully private.',
    keywords:
      'open-source database tool,AI database,natural language to SQL,AI SQL generation,Chat2SQL,Text-to-SQL,MySQL,PostgreSQL,MongoDB,Oracle,SQL Server,MariaDB,TiDB,OceanBase,Doris,StarRocks,cross-database comparison,release SQL,Excel batch import,database automation,DB-Genius,AI database copilot',
    ogTitle: 'DB-Genius | Open-Source AI Database Management Platform',
    ogDescription:
      'Open-source AI database management platform: natural-language SQL, smart workflow automation, and database comparison. Supports 10 major databases. Self-hosted — your data stays fully private.',
    ogImageAlt: 'DB-Genius open-source AI database management platform interface',
    ogLocale: 'en_US',
  },
  nav: {
    mainNav: 'Main navigation',
    features: 'Features',
    databases: 'Databases',
    showcase: 'Showcase',
    howItWorks: 'How It Works',
    faq: 'FAQ',
    login: 'Sign In',
    freeTrial: 'Try for Free',
    tryOpenSource: 'Try Open Source',
    openMenu: 'Open menu',
  },
  hero: {
    ariaLabel: 'Product introduction',
    tag: 'AI-Powered · Free & Open Source',
    titleLine1: 'AI Database Management,',
    titleLine2: 'One Sentence to SQL',
    desc: 'DB-Genius is an open-source AI database management platform: generate and execute SQL from natural language, automate workflows from Excel, and compare databases across environments. Works with 10 major databases — making data operations smarter, faster, and safer.',
    cta: 'Try It Online',
    trust1: 'Free & open source — fully auditable code',
    trust2: 'Self-hosted — your data stays private',
    trust3: 'Transparent, traceable execution',
    screenshotAlt:
      'DB-Genius AI chat interface: querying a blog database in natural language — AI generates SQL automatically and returns results in a table',
    float1: 'Natural Language → SQL',
    float2: 'Automatic warnings for risky operations',
  },
  features: {
    title: 'Core Features',
    subtitle: 'Three core capabilities covering every database management scenario',
    items: {
      sql: {
        title: 'Smart SQL Generation',
        desc: 'Describe what you need in natural language — AI generates precise SQL and executes it in real time with instant results. Handles complex queries and multi-table joins.',
      },
      workflow: {
        title: 'Workflow Automation',
        desc: 'Upload an Excel file and AI parses the data, generates batch SQL, executes it, and verifies the results. Multi-step tasks run end to end — every step transparent and traceable.',
      },
      compare: {
        title: 'Database Comparison',
        desc: 'Compare databases across production and test environments — even across different database types, comparing both schema and data. Automatically generates release SQL scripts with DDL changes and high-risk operation warnings to keep every release safe.',
      },
    },
  },
  databases: {
    ariaLabel: 'Supported databases',
    title: 'Major Databases Supported',
    subtitle: 'Full coverage of relational, document, distributed, and OLAP databases — compare schema and data across different types',
    logoAlt: '{name} database logo',
    types: {
      relational: 'Relational',
      document: 'Document',
      distributedHtap: 'Distributed HTAP',
      distributed: 'Distributed',
      olap: 'OLAP Analytics',
    },
  },
  showcase: {
    ariaLabel: 'Product showcase',
    title: 'Product Showcase',
    subtitle: 'Real UI, real capabilities — what you see is what you get',
    items: {
      sql: {
        tab: 'Natural-Language Query',
        title: 'Say the word — SQL generated and executed',
        desc: 'Describe your query in plain language. AI understands your intent, generates precise SQL, executes it in real time, and returns the results in a table. Complex queries and multi-table joins supported — every step streamed, transparent, and traceable.',
        alt: 'DB-Genius natural-language query: AI automatically generates SQL and returns article list results in a table',
      },
      intent: {
        tab: 'Transparent Execution',
        title: 'See every step of AI reasoning',
        desc: 'Intent recognition, agent routing, SQL execution, result summaries — the full reasoning and execution chain streams in real time. Inspect intermediate results anytime; AI operations are no longer a black box.',
        alt: 'DB-Genius AI intent recognition results and agent routing execution streamed in real time',
      },
      compare: {
        tab: 'Compare & Release',
        title: 'Production vs. test — differences at a glance',
        desc: 'Covers 10 major databases — relational, document, distributed, and OLAP — with cross-type comparison of schema and data. AI automatically generates release SQL scripts and warns about DDL changes and high-risk operations, making every release safe and reliable.',
        alt: 'DB-Genius database comparison: diff analysis between Pre and Test databases',
      },
      config: {
        tab: 'Connect & Document',
        title: 'Add a connection, get schema docs automatically',
        desc: 'Enter database connection details (supports 10 major databases including MySQL, PostgreSQL, Oracle, and MongoDB). The system automatically verifies connectivity and generates schema documentation, so AI understands your tables and writes SQL that fits your business.',
        alt: 'DB-Genius database configuration page: MySQL connection management and connectivity verification',
      },
    },
  },
  howItWorks: {
    title: 'How It Works',
    subtitle: 'Three simple steps to smarter database management',
    steps: {
      step1: {
        title: 'Connect Your Database',
        desc: 'Add connection details — works with MySQL, Oracle, MongoDB, and 10 major databases. Connectivity is verified automatically and schema documentation generated',
      },
      step2: {
        title: 'Chat Naturally',
        desc: 'Describe what you need in natural language — AI analyzes your intent, generates SQL, executes it, and returns the results',
      },
      step3: {
        title: 'Get Results',
        desc: 'Watch every step stream in real time, ending with complete data analysis results',
      },
    },
  },
  faq: {
    ariaLabel: 'Frequently asked questions',
    title: 'FAQ',
    subtitle: 'Everything you might want to know about DB-Genius',
    items: {
      free: {
        q: 'Is DB-Genius free and open source?',
        a: 'Yes. DB-Genius is an open-source project — you can get the source code for free and deploy it yourself, or try the online demo on our website. Open source means transparent, auditable code; deployed in your own environment, your data stays entirely under your control.',
      },
      databases: {
        q: 'Which databases are supported?',
        a: 'We currently support ten major databases: MySQL, PostgreSQL, MongoDB, Oracle, SQL Server, MariaDB, TiDB, OceanBase, Doris, and StarRocks — covering relational, document, distributed, and OLAP scenarios. You can also compare schema or data across different database types. Once a connection is added, the system automatically verifies connectivity and generates schema documentation.',
      },
      client: {
        q: 'Do I need to install a client?',
        a: 'No. DB-Genius is a browser-based (B/S) web application — once deployed, just open your browser. No client installation required, and it uses no local resources.',
      },
      safety: {
        q: 'Is AI-generated SQL safe? Could it delete data by mistake?',
        a: 'Every step of AI execution is streamed, transparent, and traceable. In comparison and release scenarios, the system automatically detects DDL changes and high-risk operations and warns you — so you can confirm the risks before anything runs.',
      },
      security: {
        q: 'Are my database credentials safe?',
        a: 'Your connection details are used only for the queries and tasks you initiate; the system verifies connectivity and generates schema documentation when a connection is added. DB-Genius is open source and self-hosted — all data and credentials stay in your own environment, with fully auditable code.',
      },
      contribute: {
        q: 'How can I contribute to the project?',
        a: 'You are welcome to contribute via Issues and Pull Requests in the GitHub repository.',
      },
    },
  },
  cta: {
    ariaLabel: 'Get started now',
    title: 'Start now — let AI manage your databases',
    subtitle: 'Free & open source · Self-hosted · Fully private data',
    button: 'Try It Online',
  },
  footer: {
    brandDesc: 'An AI-driven database management platform that makes data operations smarter, faster, and safer.',
    product: 'Product',
    support: 'Support',
    productNav: 'Product navigation',
    supportNav: 'Support navigation',
    features: 'Features',
    showcase: 'Showcase',
    howItWorks: 'How It Works',
    faq: 'FAQ',
    login: 'Sign In',
    tagline: 'AI-driven database management platform.',
  },
}
