<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

type DbTypeKey = 'relational' | 'document' | 'distributedHtap' | 'distributed' | 'olap'

const databases: { name: string; logo: string; typeKey: DbTypeKey }[] = [
  { name: 'MySQL', logo: '/landing/db-logos/mysql.svg', typeKey: 'relational' },
  { name: 'PostgreSQL', logo: '/landing/db-logos/postgresql.svg', typeKey: 'relational' },
  { name: 'MongoDB', logo: '/landing/db-logos/mongodb.svg', typeKey: 'document' },
  { name: 'Oracle', logo: '/landing/db-logos/oracle.svg', typeKey: 'relational' },
  { name: 'SQL Server', logo: '/landing/db-logos/microsoftsqlserver.svg', typeKey: 'relational' },
  { name: 'MariaDB', logo: '/landing/db-logos/mariadb.svg', typeKey: 'relational' },
  { name: 'TiDB', logo: '/landing/db-logos/tidb.svg', typeKey: 'distributedHtap' },
  { name: 'OceanBase', logo: '/landing/db-logos/oceanbase.svg', typeKey: 'distributed' },
  { name: 'Doris', logo: '/landing/db-logos/apachedoris.svg', typeKey: 'olap' },
  { name: 'StarRocks', logo: '/landing/db-logos/starrocks.svg', typeKey: 'olap' },
]

const items = computed(() =>
  databases.map((db) => ({
    ...db,
    type: t(`landing.databases.types.${db.typeKey}`),
    alt: t('landing.databases.logoAlt', { name: db.name }),
  })),
)
</script>

<template>
  <section id="databases" class="databases" :aria-label="$t('landing.databases.ariaLabel')">
    <div class="databases-inner">
      <div class="section-header">
        <h2>{{ $t('landing.databases.title') }}</h2>
        <p>{{ $t('landing.databases.subtitle') }}</p>
      </div>
      <ul class="db-grid">
        <li v-for="db in items" :key="db.name" class="db-tile">
          <img :src="db.logo" :alt="db.alt" width="40" height="40" loading="lazy" />
          <span class="db-name">{{ db.name }}</span>
          <span class="db-type">{{ db.type }}</span>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped lang="scss">
.databases {
  padding: 80px 24px;
  background: #fff;
  border-top: 1px solid var(--color-border-1);
}

.databases-inner {
  max-width: 1200px;
  margin: 0 auto;
}

.section-header {
  text-align: center;
  margin-bottom: 40px;

  h2 {
    font-size: 32px;
    font-weight: 700;
    color: var(--color-text-1);
    margin-bottom: 8px;
  }

  p {
    font-size: 16px;
    color: var(--color-text-3);
    max-width: 640px;
    margin: 0 auto;
  }
}

.db-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

.db-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px 12px;
  border: 1px solid var(--color-border-1);
  border-radius: 12px;
  background: #fff;
  transition: all 0.25s;

  img {
    width: 40px;
    height: 40px;
    filter: grayscale(1) opacity(0.55);
    transition: filter 0.25s;
  }

  .db-name {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-text-1);
  }

  .db-type {
    font-size: 12px;
    color: var(--color-text-4);
  }

  &:hover {
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
    transform: translateY(-2px);

    img {
      filter: none;
    }
  }
}

@media (max-width: 900px) {
  .databases {
    padding: 56px 20px;
  }

  .db-grid {
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }

  .db-tile {
    padding: 16px 8px;
  }
}

@media (max-width: 480px) {
  .db-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
