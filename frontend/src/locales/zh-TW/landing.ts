// landing 命名空間：落地頁所有面向用戶的文案（繁體中文）
export default {
  meta: {
    title: 'DB-Genius | 開源 AI 資料庫管理大師 - 自然語言生成 SQL · 智慧工作流程 · 資料庫對比分析',
    description:
      'DB-Genius 是開源的 AI 資料庫管理平台：用自然語言生成並執行 SQL、上傳 Excel 自動完成批次資料工作流程、對比不同環境資料庫差異並生成安全的發版腳本。支援 MySQL、PostgreSQL、MongoDB、Oracle、SQL Server、MariaDB、TiDB、OceanBase、Doris、StarRocks 十種主流資料庫，不同類型之間可相互對比。開源自部署，資料完全私有。',
    keywords:
      '開源資料庫工具,AI 資料庫,自然語言轉 SQL,AI SQL 生成,Chat2SQL,Text-to-SQL,MySQL,PostgreSQL,MongoDB,Oracle,SQL Server,MariaDB,TiDB,OceanBase,Doris,StarRocks,跨資料庫對比,發版 SQL,Excel 批次匯入,資料庫自動化,DB-Genius,AI 資料庫大師',
    ogTitle: 'DB-Genius | 開源 AI 資料庫管理大師',
    ogDescription:
      '開源的 AI 資料庫管理平台：自然語言生成 SQL、智慧工作流程自動化、資料庫對比分析。支援 10 種主流資料庫，開源自部署，資料完全私有。',
    ogImageAlt: 'DB-Genius 開源 AI 資料庫管理平台產品介面',
    ogLocale: 'zh_TW',
  },
  nav: {
    mainNav: '主導覽',
    features: '核心功能',
    databases: '支援資料庫',
    showcase: '產品展示',
    howItWorks: '工作流程',
    faq: '常見問題',
    login: '登入系統',
    freeTrial: '免費體驗',
    tryOpenSource: '體驗開源版',
    openMenu: '開啟選單',
  },
  hero: {
    ariaLabel: '產品介紹',
    tag: 'AI 驅動 · 開源免費',
    titleLine1: 'AI 資料庫管理大師',
    titleLine2: '一句話搞定 SQL',
    desc: 'DB-Genius 是開源的 AI 資料庫管理平台：自然語言生成並執行 SQL、Excel 智慧工作流程自動化、資料庫對比分析。支援 10 種主流資料庫，讓資料操作更智慧、更高效、更安全。',
    cta: '開始線上體驗',
    trust1: '開源免費，程式碼透明可稽核',
    trust2: '支援自部署，資料完全私有',
    trust3: '執行過程透明可追蹤',
    screenshotAlt: 'DB-Genius AI 對話介面：用自然語言查詢部落格資料庫，AI 自動生成 SQL 並以表格回傳查詢結果',
    float1: '自然語言 → SQL',
    float2: '高危操作自動警告',
  },
  features: {
    title: '核心功能',
    subtitle: '三大核心能力，涵蓋資料庫管理全場景',
    items: {
      sql: {
        title: '智慧 SQL 生成',
        desc: '用自然語言描述需求，AI 自動生成精準 SQL 語句並即時執行，結果即時回饋。支援複雜查詢、多表關聯。',
      },
      workflow: {
        title: '工作流程自動化',
        desc: '上傳 Excel 檔案，AI 自動解析資料、生成批次 SQL、執行並驗證。多步驟任務全自動完成，每步透明可追蹤。',
      },
      compare: {
        title: '資料庫對比分析',
        desc: '對比生產與測試環境資料庫差異，不同類型資料庫之間也能相互對比結構與資料。自動生成發版 SQL 腳本，包含 DDL 變更、高危操作警告，確保發佈安全。',
      },
    },
  },
  databases: {
    ariaLabel: '支援的資料庫',
    title: '支援主流資料庫',
    subtitle: '關聯式、文件型、分散式與 OLAP 分析型資料庫全涵蓋，不同類型之間可相互對比結構與資料',
    logoAlt: '{name} 資料庫 Logo',
    types: {
      relational: '關聯式',
      document: '文件型',
      distributedHtap: '分散式 HTAP',
      distributed: '分散式',
      olap: 'OLAP 分析',
    },
  },
  showcase: {
    ariaLabel: '產品功能展示',
    title: '產品展示',
    subtitle: '真實介面，真實能力 —— 所見即所得',
    items: {
      sql: {
        tab: '自然語言查資料',
        title: '說一句話，SQL 自動生成並執行',
        desc: '用中文描述你的查詢需求，AI 自動識別意圖、生成精準 SQL、即時執行並以表格回傳結果。支援複雜查詢與多表關聯，每一步串流展示、透明可追蹤。',
        alt: 'DB-Genius 自然語言查詢：AI 自動生成 SQL 並回傳文章列表查詢結果表格',
      },
      intent: {
        tab: '透明執行過程',
        title: 'AI 的每一步思考，你都看得見',
        desc: '意圖識別、智慧體路由、SQL 執行、結果總結——完整的推理與執行鏈路即時串流呈現，可隨時查看中間結果，讓 AI 操作不再黑箱。',
        alt: 'DB-Genius AI 意圖識別結果與智慧體路由執行過程即時串流展示',
      },
      compare: {
        tab: '環境對比發版',
        title: '生產 vs 測試，差異一目瞭然',
        desc: '涵蓋關聯式、文件型、分散式與 OLAP 等 10 種主流資料庫，不同類型之間也能相互對比結構與資料差異。AI 自動生成發版 SQL 腳本，並對 DDL 變更與高危操作給出警告，讓每次發佈都安全可靠。',
        alt: 'DB-Genius 資料庫對比功能：選擇 Pre 與 Test 資料庫進行差異分析',
      },
      config: {
        tab: '連線即文件',
        title: '新增連線，自動生成結構文件',
        desc: '填入資料庫連線資訊（支援 MySQL、PostgreSQL、Oracle、MongoDB 等 10 種主流資料庫），系統自動驗證連通性並生成資料庫結構文件，AI 藉此理解你的表結構，生成更貼合業務的 SQL。',
        alt: 'DB-Genius 資料庫設定頁面：MySQL 連線管理與連通性驗證',
      },
    },
  },
  howItWorks: {
    title: '工作流程',
    subtitle: '簡單三步，開啟智慧資料庫管理之旅',
    steps: {
      step1: {
        title: '設定資料庫',
        desc: '新增資料庫連線資訊，支援 MySQL、Oracle、MongoDB 等 10 種主流資料庫，自動驗證連通性並生成結構文件',
      },
      step2: {
        title: '對話式互動',
        desc: '用自然語言描述需求，AI 自動分析意圖、生成 SQL、執行並回傳結果',
      },
      step3: {
        title: '取得結果',
        desc: '即時串流展示每一步執行過程，最終呈現完整的資料分析結果',
      },
    },
  },
  faq: {
    ariaLabel: '常見問題',
    title: '常見問題',
    subtitle: '關於 DB-Genius，你可能想瞭解這些',
    items: {
      free: {
        q: 'DB-Genius 是開源免費的嗎？',
        a: '是的。DB-Genius 是開源專案，可以免費取得原始碼並自行部署使用，也可以直接在官網體驗線上示範。開源意味著程式碼透明可稽核，部署在自己的環境中，資料完全由你掌控。',
      },
      databases: {
        q: '支援哪些資料庫？',
        a: '目前支援 MySQL、PostgreSQL、MongoDB、Oracle、SQL Server、MariaDB、TiDB、OceanBase、Doris、StarRocks 十種主流資料庫，涵蓋關聯式、文件型、分散式與 OLAP 分析型場景；不同類型的資料庫之間也可以相互對比結構或資料差異。新增連線後系統會自動驗證連通性並生成結構文件。',
      },
      client: {
        q: '需要下載安裝用戶端嗎？',
        a: '不需要。DB-Genius 是 B/S 架構的網頁應用，部署完成後開啟瀏覽器即可使用，無需安裝任何用戶端，也不佔用本機資源。',
      },
      safety: {
        q: 'AI 生成的 SQL 安全嗎？會不會誤刪資料？',
        a: 'AI 的每一步執行過程都會串流展示、透明可追蹤；在資料庫對比與發版場景中，系統會自動識別 DDL 變更與高危操作並給出警告，幫助你在執行前確認風險。',
      },
      security: {
        q: '我的資料庫連線資訊安全嗎？',
        a: '資料庫連線資訊僅用於你發起的查詢與任務，系統會在新增連線時驗證連通性並生成結構文件。DB-Genius 開源自部署，所有資料與連線資訊都儲存在你自己的環境中，程式碼透明可稽核。',
      },
      contribute: {
        q: '如何為專案貢獻？',
        a: '歡迎透過 GitHub 儲存庫提交 Issue 與 Pull Request 參與共建。',
      },
    },
  },
  cta: {
    ariaLabel: '立即開始',
    title: '現在開始，讓 AI 幫你管理資料庫',
    subtitle: '開源免費 · 支援自部署 · 資料完全私有',
    button: '開始線上體驗',
  },
  footer: {
    brandDesc: 'AI 驅動的資料庫管理平台，讓資料操作更智慧、更高效、更安全。',
    product: '產品',
    support: '支援',
    productNav: '產品導覽',
    supportNav: '支援導覽',
    features: '核心功能',
    showcase: '產品展示',
    howItWorks: '工作流程',
    faq: '常見問題',
    login: '登入系統',
    tagline: 'AI 驅動的資料庫管理平台。',
  },
}
