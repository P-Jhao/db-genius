// landing namespace: all user-facing landing page copy (Français)
export default {
  meta: {
    title: 'DB-Genius | Gestion de bases de données par IA open source - SQL en langage naturel · Flux de travail intelligents · Comparaison de bases',
    description:
      'DB-Genius est une plateforme open source de gestion de bases de données par IA : générez et exécutez du SQL en langage naturel, automatisez des traitements par lots depuis Excel et comparez vos bases entre environnements avec des scripts de déploiement sûrs. Compatible avec dix bases majeures : MySQL, PostgreSQL, MongoDB, Oracle, SQL Server, MariaDB, TiDB, OceanBase, Doris et StarRocks, avec comparaison entre différents types. Open source et auto-hébergée : vos données restent totalement privées.',
    keywords:
      'outil de base de données open source,base de données IA,langage naturel vers SQL,génération de SQL par IA,Chat2SQL,Text-to-SQL,MySQL,PostgreSQL,MongoDB,Oracle,SQL Server,MariaDB,TiDB,OceanBase,Doris,StarRocks,comparaison de bases de données,SQL de déploiement,import Excel par lots,automatisation de bases de données,DB-Genius',
    ogTitle: 'DB-Genius | Plateforme open source de gestion de bases de données par IA',
    ogDescription:
      'Plateforme open source de gestion de bases de données par IA : SQL en langage naturel, automatisation des flux de travail et comparaison de bases de données. Compatible avec 10 bases majeures. Auto-hébergée : données 100 % privées.',
    ogImageAlt: 'Interface de DB-Genius, plateforme open source de gestion de bases de données par IA',
    ogLocale: 'fr_FR',
  },
  nav: {
    mainNav: 'Navigation principale',
    features: 'Fonctionnalités',
    databases: 'Bases de données',
    showcase: 'Démonstration',
    howItWorks: 'Fonctionnement',
    faq: 'FAQ',
    login: 'Se connecter',
    freeTrial: 'Essai gratuit',
    tryOpenSource: 'Essayer la version open source',
    openMenu: 'Ouvrir le menu',
  },
  hero: {
    ariaLabel: 'Présentation du produit',
    tag: 'Propulsé par l’IA · Gratuit et open source',
    titleLine1: 'Gestion de bases de données par IA,',
    titleLine2: 'du SQL en une phrase',
    desc: 'DB-Genius est une plateforme open source de gestion de bases de données par IA : générez et exécutez du SQL en langage naturel, automatisez vos flux de travail depuis Excel et comparez vos bases entre environnements. Compatible avec 10 bases de données majeures, pour des opérations plus intelligentes, plus rapides et plus sûres.',
    cta: 'Essayer en ligne',
    trust1: 'Gratuit et open source : code auditable',
    trust2: 'Auto-hébergé : données 100 % privées',
    trust3: 'Exécution transparente et traçable',
    screenshotAlt:
      'Interface de chat IA de DB-Genius : requête en langage naturel sur une base de données de blog — l’IA génère automatiquement le SQL et renvoie les résultats dans un tableau',
    float1: 'Langage naturel → SQL',
    float2: 'Alertes automatiques sur les opérations à risque',
  },
  features: {
    title: 'Fonctionnalités clés',
    subtitle: 'Trois capacités essentielles couvrant tous les scénarios de gestion de bases de données',
    items: {
      sql: {
        title: 'Génération intelligente de SQL',
        desc: 'Décrivez votre besoin en langage naturel : l’IA génère un SQL précis et l’exécute en temps réel, avec des résultats immédiats. Requêtes complexes et jointures multi-tables prises en charge.',
      },
      workflow: {
        title: 'Automatisation des flux de travail',
        desc: 'Téléversez un fichier Excel : l’IA analyse les données, génère le SQL par lots, l’exécute et vérifie les résultats. Les tâches en plusieurs étapes s’enchaînent automatiquement, chaque étape restant transparente et traçable.',
      },
      compare: {
        title: 'Comparaison de bases de données',
        desc: 'Comparez les bases de production et de test, y compris entre différents types de bases, sur la structure comme sur les données. Génère automatiquement des scripts SQL de déploiement avec les changements DDL et des alertes sur les opérations à haut risque, pour des mises en production en toute sécurité.',
      },
    },
  },
  databases: {
    ariaLabel: 'Bases de données prises en charge',
    title: 'Prise en charge des principales bases de données',
    subtitle: 'Couverture complète des bases relationnelles, documentaires, distribuées et OLAP, avec comparaison de structure et de données entre différents types',
    logoAlt: 'Logo de la base de données {name}',
    types: {
      relational: 'Relationnelle',
      document: 'Documentaire',
      distributedHtap: 'HTAP distribuée',
      distributed: 'Distribuée',
      olap: 'Analytique OLAP',
    },
  },
  showcase: {
    ariaLabel: 'Démonstration du produit',
    title: 'Le produit en images',
    subtitle: 'Interface réelle, capacités réelles : ce que vous voyez est ce que vous obtenez',
    items: {
      sql: {
        tab: 'Requête en langage naturel',
        title: 'Une phrase suffit : le SQL est généré et exécuté',
        desc: 'Décrivez votre requête en langage naturel. L’IA comprend votre intention, génère un SQL précis, l’exécute en temps réel et renvoie les résultats dans un tableau. Requêtes complexes et jointures multi-tables prises en charge ; chaque étape est diffusée en continu, de façon transparente et traçable.',
        alt: 'Requête en langage naturel de DB-Genius : l’IA génère automatiquement le SQL et renvoie la liste des articles dans un tableau',
      },
      intent: {
        tab: 'Exécution transparente',
        title: 'Chaque étape du raisonnement de l’IA, sous vos yeux',
        desc: 'Reconnaissance d’intention, routage des agents, exécution du SQL, synthèse des résultats : toute la chaîne de raisonnement et d’exécution est diffusée en temps réel. Consultez les résultats intermédiaires à tout moment : l’IA n’est plus une boîte noire.',
        alt: 'Résultats de reconnaissance d’intention et routage des agents de DB-Genius diffusés en temps réel',
      },
      compare: {
        tab: 'Comparer et déployer',
        title: 'Production vs test : les différences en un coup d’œil',
        desc: 'Couvre 10 bases de données majeures — relationnelles, documentaires, distribuées et OLAP — avec comparaison de structure et de données entre différents types. L’IA génère automatiquement les scripts SQL de déploiement et signale les changements DDL et les opérations à haut risque, pour des mises en production sûres et fiables.',
        alt: 'Comparaison de bases de données DB-Genius : analyse des différences entre les bases Pre et Test',
      },
      config: {
        tab: 'Connexion documentée',
        title: 'Ajoutez une connexion, obtenez la documentation du schéma',
        desc: 'Saisissez les informations de connexion (compatible avec 10 bases majeures, dont MySQL, PostgreSQL, Oracle et MongoDB). Le système vérifie automatiquement la connectivité et génère la documentation de la structure, afin que l’IA comprenne vos tables et produise un SQL adapté à votre métier.',
        alt: 'Page de configuration des bases de données DB-Genius : gestion des connexions MySQL et vérification de la connectivité',
      },
    },
  },
  howItWorks: {
    title: 'Fonctionnement',
    subtitle: 'Trois étapes simples vers une gestion intelligente de vos bases de données',
    steps: {
      step1: {
        title: 'Configurez la base',
        desc: 'Ajoutez les informations de connexion — compatible avec MySQL, Oracle, MongoDB et 10 bases majeures. La connectivité est vérifiée automatiquement et la documentation de la structure est générée',
      },
      step2: {
        title: 'Dialoguez naturellement',
        desc: 'Décrivez votre besoin en langage naturel : l’IA analyse votre intention, génère le SQL, l’exécute et renvoie les résultats',
      },
      step3: {
        title: 'Obtenez les résultats',
        desc: 'Suivez chaque étape de l’exécution en temps réel, jusqu’aux résultats complets de l’analyse des données',
      },
    },
  },
  faq: {
    ariaLabel: 'Questions fréquentes',
    title: 'Questions fréquentes',
    subtitle: 'Tout ce que vous souhaitez peut-être savoir sur DB-Genius',
    items: {
      free: {
        q: 'DB-Genius est-il gratuit et open source ?',
        a: 'Oui. DB-Genius est un projet open source : vous pouvez obtenir gratuitement le code source et le déployer vous-même, ou essayer la démo en ligne sur notre site. L’open source garantit un code transparent et auditable ; déployé dans votre propre environnement, vos données restent entièrement sous votre contrôle.',
      },
      databases: {
        q: 'Quelles bases de données sont prises en charge ?',
        a: 'Nous prenons actuellement en charge dix bases de données majeures : MySQL, PostgreSQL, MongoDB, Oracle, SQL Server, MariaDB, TiDB, OceanBase, Doris et StarRocks, couvrant les scénarios relationnels, documentaires, distribués et OLAP. Vous pouvez également comparer la structure ou les données entre différents types de bases. À l’ajout d’une connexion, le système vérifie automatiquement la connectivité et génère la documentation de la structure.',
      },
      client: {
        q: 'Dois-je installer un client ?',
        a: 'Non. DB-Genius est une application web en architecture B/S : une fois déployée, il suffit d’ouvrir votre navigateur. Aucun client à installer et aucune ressource locale consommée.',
      },
      safety: {
        q: 'Le SQL généré par IA est-il sûr ? Peut-il supprimer des données par erreur ?',
        a: 'Chaque étape de l’exécution de l’IA est diffusée en continu, de façon transparente et traçable. Dans les scénarios de comparaison et de déploiement, le système identifie automatiquement les changements DDL et les opérations à haut risque et vous alerte, afin de confirmer les risques avant exécution.',
      },
      security: {
        q: 'Mes informations de connexion sont-elles en sécurité ?',
        a: 'Vos informations de connexion ne servent qu’aux requêtes et tâches que vous lancez ; le système vérifie la connectivité et génère la documentation de la structure lors de l’ajout d’une connexion. DB-Genius est open source et auto-hébergé : toutes les données et informations de connexion restent dans votre propre environnement, avec un code transparent et auditable.',
      },
      contribute: {
        q: 'Comment contribuer ou envisager un partenariat ?',
        a: 'Vous pouvez contribuer via des Issues et des Pull Requests sur le dépôt GitHub.',
      },
    },
  },
  cta: {
    ariaLabel: 'Commencer maintenant',
    title: 'Commencez maintenant : laissez l’IA gérer vos bases de données',
    subtitle: 'Gratuit et open source · Auto-hébergé · Données 100 % privées',
    button: 'Essayer en ligne',
  },
  footer: {
    brandDesc: 'Plateforme de gestion de bases de données propulsée par l’IA, pour des opérations plus intelligentes, plus rapides et plus sûres.',
    product: 'Produit',
    support: 'Assistance',
    productNav: 'Navigation produit',
    supportNav: 'Navigation assistance',
    features: 'Fonctionnalités',
    showcase: 'Démonstration',
    howItWorks: 'Fonctionnement',
    faq: 'FAQ',
    login: 'Se connecter',
    tagline: 'Plateforme de gestion de bases de données propulsée par l’IA.',
  },
}
