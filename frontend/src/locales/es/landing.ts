// landing namespace: all user-facing landing page copy (Español)
export default {
  meta: {
    title: 'DB-Genius | Gestión de bases de datos con IA de código abierto - SQL en lenguaje natural · Flujos de trabajo inteligentes · Comparación de bases de datos',
    description:
      'DB-Genius es una plataforma open source de gestión de bases de datos con IA: genera y ejecuta SQL a partir de lenguaje natural, automatiza flujos de trabajo por lotes desde Excel y compara bases de datos entre entornos generando scripts de despliegue seguros. Compatible con diez bases de datos principales: MySQL, PostgreSQL, MongoDB, Oracle, SQL Server, MariaDB, TiDB, OceanBase, Doris y StarRocks, con comparación entre distintos tipos. Open source y autoalojado: tus datos son totalmente privados.',
    keywords:
      'herramienta de base de datos open source,base de datos con IA,lenguaje natural a SQL,generación de SQL con IA,Chat2SQL,Text-to-SQL,MySQL,PostgreSQL,MongoDB,Oracle,SQL Server,MariaDB,TiDB,OceanBase,Doris,StarRocks,comparación de bases de datos,SQL de despliegue,importación masiva desde Excel,automatización de bases de datos,DB-Genius',
    ogTitle: 'DB-Genius | Plataforma open source de gestión de bases de datos con IA',
    ogDescription:
      'Plataforma open source de gestión de bases de datos con IA: SQL en lenguaje natural, automatización de flujos de trabajo y comparación de bases de datos. Compatible con 10 bases de datos principales. Autoalojada: tus datos son 100 % privados.',
    ogImageAlt: 'Interfaz de DB-Genius, plataforma open source de gestión de bases de datos con IA',
    ogLocale: 'es_ES',
  },
  nav: {
    mainNav: 'Navegación principal',
    features: 'Funciones',
    databases: 'Bases de datos',
    showcase: 'Producto',
    howItWorks: 'Cómo funciona',
    faq: 'Preguntas frecuentes',
    login: 'Iniciar sesión',
    freeTrial: 'Prueba gratis',
    tryOpenSource: 'Probar versión open source',
    openMenu: 'Abrir menú',
  },
  hero: {
    ariaLabel: 'Presentación del producto',
    tag: 'Impulsado por IA · Gratuito y de código abierto',
    titleLine1: 'Gestión de bases de datos con IA,',
    titleLine2: 'SQL con una sola frase',
    desc: 'DB-Genius es una plataforma open source de gestión de bases de datos con IA: genera y ejecuta SQL a partir de lenguaje natural, automatiza flujos de trabajo desde Excel y compara bases de datos entre entornos. Compatible con 10 bases de datos principales: operaciones de datos más inteligentes, rápidas y seguras.',
    cta: 'Probar en línea',
    trust1: 'Gratuito y de código abierto: código auditable',
    trust2: 'Autoalojado: tus datos son 100 % privados',
    trust3: 'Ejecución transparente y trazable',
    screenshotAlt:
      'Interfaz de chat con IA de DB-Genius: consulta en lenguaje natural a una base de datos de blog; la IA genera el SQL automáticamente y devuelve los resultados en una tabla',
    float1: 'Lenguaje natural → SQL',
    float2: 'Avisos automáticos de operaciones de riesgo',
  },
  features: {
    title: 'Funciones principales',
    subtitle: 'Tres capacidades esenciales que cubren todos los escenarios de gestión de bases de datos',
    items: {
      sql: {
        title: 'Generación inteligente de SQL',
        desc: 'Describe lo que necesitas en lenguaje natural: la IA genera SQL preciso y lo ejecuta en tiempo real con resultados inmediatos. Admite consultas complejas y uniones entre varias tablas.',
      },
      workflow: {
        title: 'Automatización de flujos de trabajo',
        desc: 'Sube un archivo Excel y la IA analiza los datos, genera SQL por lotes, lo ejecuta y verifica los resultados. Tareas de varios pasos de forma totalmente automática, cada paso transparente y trazable.',
      },
      compare: {
        title: 'Comparación de bases de datos',
        desc: 'Compara las diferencias entre bases de datos de producción y de pruebas, incluso entre distintos tipos de base de datos, tanto en estructura como en datos. Genera automáticamente scripts SQL de despliegue con cambios DDL y avisos de operaciones de alto riesgo para garantizar publicaciones seguras.',
      },
    },
  },
  databases: {
    ariaLabel: 'Bases de datos compatibles',
    title: 'Compatibilidad con las principales bases de datos',
    subtitle: 'Cobertura total de bases de datos relacionales, de documentos, distribuidas y OLAP, con comparación de estructura y datos entre distintos tipos',
    logoAlt: 'Logotipo de la base de datos {name}',
    types: {
      relational: 'Relacional',
      document: 'De documentos',
      distributedHtap: 'HTAP distribuida',
      distributed: 'Distribuida',
      olap: 'Analítica OLAP',
    },
  },
  showcase: {
    ariaLabel: 'Demostración del producto',
    title: 'El producto en acción',
    subtitle: 'Interfaz real, capacidades reales: lo que ves es lo que obtienes',
    items: {
      sql: {
        tab: 'Consulta en lenguaje natural',
        title: 'Di una frase: el SQL se genera y se ejecuta solo',
        desc: 'Describe tu consulta en lenguaje natural. La IA comprende tu intención, genera SQL preciso, lo ejecuta en tiempo real y devuelve los resultados en una tabla. Admite consultas complejas y uniones entre tablas; cada paso se muestra en streaming, de forma transparente y trazable.',
        alt: 'Consulta en lenguaje natural de DB-Genius: la IA genera SQL automáticamente y devuelve la lista de artículos en una tabla',
      },
      intent: {
        tab: 'Ejecución transparente',
        title: 'Cada paso del razonamiento de la IA, a la vista',
        desc: 'Reconocimiento de intención, enrutamiento de agentes, ejecución de SQL y resumen de resultados: toda la cadena de razonamiento y ejecución se muestra en streaming en tiempo real. Consulta los resultados intermedios en cualquier momento: la IA deja de ser una caja negra.',
        alt: 'Reconocimiento de intención de la IA de DB-Genius y enrutamiento de agentes mostrados en streaming en tiempo real',
      },
      compare: {
        tab: 'Comparar y publicar',
        title: 'Producción vs. pruebas: diferencias a primera vista',
        desc: 'Cubre 10 bases de datos principales (relacionales, de documentos, distribuidas y OLAP) y permite comparar estructura y datos entre distintos tipos. La IA genera automáticamente scripts SQL de despliegue y avisa de cambios DDL y operaciones de alto riesgo, para que cada publicación sea segura y fiable.',
        alt: 'Comparación de bases de datos de DB-Genius: análisis de diferencias entre las bases de datos Pre y Test',
      },
      config: {
        tab: 'Conexión documentada',
        title: 'Añade una conexión y obtén la documentación del esquema',
        desc: 'Introduce los datos de conexión (compatible con 10 bases de datos principales como MySQL, PostgreSQL, Oracle y MongoDB). El sistema verifica automáticamente la conectividad y genera la documentación de la estructura, para que la IA entienda tus tablas y genere SQL adaptado a tu negocio.',
        alt: 'Página de configuración de bases de datos de DB-Genius: gestión de conexiones MySQL y verificación de conectividad',
      },
    },
  },
  howItWorks: {
    title: 'Cómo funciona',
    subtitle: 'Tres sencillos pasos para una gestión inteligente de bases de datos',
    steps: {
      step1: {
        title: 'Configura la base de datos',
        desc: 'Añade los datos de conexión: compatible con MySQL, Oracle, MongoDB y otras 10 bases de datos principales. La conectividad se verifica automáticamente y se genera la documentación de la estructura',
      },
      step2: {
        title: 'Interactúa conversando',
        desc: 'Describe lo que necesitas en lenguaje natural: la IA analiza tu intención, genera el SQL, lo ejecuta y devuelve los resultados',
      },
      step3: {
        title: 'Obtén los resultados',
        desc: 'Sigue cada paso de la ejecución en streaming y en tiempo real, hasta obtener el análisis de datos completo',
      },
    },
  },
  faq: {
    ariaLabel: 'Preguntas frecuentes',
    title: 'Preguntas frecuentes',
    subtitle: 'Todo lo que quizá quieras saber sobre DB-Genius',
    items: {
      free: {
        q: '¿DB-Genius es gratuito y de código abierto?',
        a: 'Sí. DB-Genius es un proyecto de código abierto: puedes obtener el código fuente gratis y desplegarlo por tu cuenta, o probar la demo en línea en nuestro sitio web. El código abierto significa transparencia y auditabilidad; al desplegarlo en tu propio entorno, tus datos están totalmente bajo tu control.',
      },
      databases: {
        q: '¿Qué bases de datos son compatibles?',
        a: 'Actualmente somos compatibles con diez bases de datos principales: MySQL, PostgreSQL, MongoDB, Oracle, SQL Server, MariaDB, TiDB, OceanBase, Doris y StarRocks, que cubren escenarios relacionales, de documentos, distribuidos y OLAP. También puedes comparar la estructura o los datos entre distintos tipos de bases de datos. Al añadir una conexión, el sistema verifica automáticamente la conectividad y genera la documentación de la estructura.',
      },
      client: {
        q: '¿Necesito descargar e instalar un cliente?',
        a: 'No. DB-Genius es una aplicación web con arquitectura B/S: una vez desplegada, solo tienes que abrir el navegador. No requiere instalar ningún cliente ni consume recursos locales.',
      },
      safety: {
        q: '¿Es seguro el SQL generado por IA? ¿Podría borrar datos por error?',
        a: 'Cada paso de la ejecución de la IA se muestra en streaming, de forma transparente y trazable. En los escenarios de comparación y despliegue, el sistema identifica automáticamente los cambios DDL y las operaciones de alto riesgo y te avisa, para que confirmes los riesgos antes de ejecutar.',
      },
      security: {
        q: '¿Están seguros mis datos de conexión?',
        a: 'Los datos de conexión solo se utilizan para las consultas y tareas que tú inicias; el sistema verifica la conectividad y genera la documentación de la estructura al añadir la conexión. DB-Genius es open source y autoalojado: todos los datos y credenciales permanecen en tu propio entorno, con código transparente y auditable.',
      },
      contribute: {
        q: '¿Cómo puedo contribuir al proyecto?',
        a: 'Te invitamos a contribuir con Issues y Pull Requests en el repositorio de GitHub.',
      },
    },
  },
  cta: {
    ariaLabel: 'Empieza ahora',
    title: 'Empieza ahora: deja que la IA gestione tus bases de datos',
    subtitle: 'Gratuito y open source · Autoalojado · Datos 100 % privados',
    button: 'Probar en línea',
  },
  footer: {
    brandDesc: 'Plataforma de gestión de bases de datos impulsada por IA: operaciones de datos más inteligentes, rápidas y seguras.',
    product: 'Producto',
    support: 'Soporte',
    productNav: 'Navegación del producto',
    supportNav: 'Navegación de soporte',
    features: 'Funciones',
    showcase: 'Producto',
    howItWorks: 'Cómo funciona',
    faq: 'Preguntas frecuentes',
    login: 'Iniciar sesión',
    tagline: 'Plataforma de gestión de bases de datos impulsada por IA.',
  },
}
