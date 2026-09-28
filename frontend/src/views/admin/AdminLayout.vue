<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useUserStore } from '../../stores/user'
import LanguageSwitcher from '../../components/common/LanguageSwitcher.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const collapsed = ref(false)
const mobileDrawer = ref(false)

const currentPath = computed(() => route.path)

const menuItems = computed(() => [
  { key: '/admin/chat', icon: 'icon-message', label: t('admin.layout.menuChat') },
  { key: '/admin/db-config', icon: 'icon-storage', label: t('admin.layout.menuDbConfig') },
  { key: '/admin/model-config', icon: 'icon-robot', label: t('admin.layout.menuModelConfig') },
  { key: '/admin/conversations', icon: 'icon-history', label: t('admin.layout.menuConversations') },
])

function handleMenuClick(key: string) {
  router.push(key)
  mobileDrawer.value = false
}

function goHome() {
  mobileDrawer.value = false
  router.push('/')
}

function handleLogout() {
  userStore.logout()
}

watch(() => route.path, () => {
  mobileDrawer.value = false
})
</script>

<template>
  <a-layout class="admin-layout">
    <a-layout-sider
      v-if="!mobileDrawer"
      class="admin-sider desktop-sider"
      :collapsed="collapsed"
      collapsible
      hide-trigger
      :width="200"
      :collapsed-width="56"
      breakpoint="lg"
      @collapse="collapsed = $event"
    >
      <div class="sider-logo" :class="{ collapsed }" @click="goHome">
        <svg width="28" height="28" viewBox="0 0 48 48" fill="none">
          <defs>
            <linearGradient id="sider-g" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#165DFF" />
              <stop offset="100%" stop-color="#14C9C9" />
            </linearGradient>
          </defs>
          <rect width="48" height="48" rx="10" fill="url(#sider-g)" />
          <text x="24" y="33" text-anchor="middle" font-size="22" font-weight="700" fill="#fff" font-family="system-ui">DB</text>
        </svg>
        <span v-if="!collapsed" class="logo-text">DB-Genius</span>
      </div>
      <a-menu
        :selected-keys="[currentPath]"
        :auto-open-selected="true"
        @menu-item-click="handleMenuClick"
      >
        <a-menu-item v-for="item in menuItems" :key="item.key">
          <template #icon><component :is="item.icon" /></template>
          {{ item.label }}
        </a-menu-item>
      </a-menu>
      <div class="sider-footer" :class="{ collapsed }">
        <a-divider :margin="12" />
        <div class="user-info">
          <a-avatar :size="28" :style="{ backgroundColor: '#165DFF' }">
            {{ userStore.nickname?.charAt(0) || userStore.username.charAt(0) }}
          </a-avatar>
          <span v-if="!collapsed" class="user-name">{{ userStore.nickname || userStore.username }}</span>
          <LanguageSwitcher v-if="!collapsed" />
        </div>
        <div v-if="!collapsed" class="footer-actions">
          <a-tooltip :content="$t('admin.layout.collapseMenu')">
            <a-button size="small" @click="collapsed = true">
              <template #icon><icon-shrink /></template>
            </a-button>
          </a-tooltip>
          <a-tooltip :content="$t('admin.layout.logout')">
            <a-button size="small" status="danger" @click="handleLogout">
              <template #icon><icon-export /></template>
            </a-button>
          </a-tooltip>
        </div>
        <div v-else class="footer-actions collapsed-actions">
          <a-tooltip :content="$t('admin.layout.expandMenu')">
            <a-button size="small" @click="collapsed = false">
              <template #icon><icon-right /></template>
            </a-button>
          </a-tooltip>
          <a-tooltip :content="$t('admin.layout.logout')">
            <a-button size="small" status="danger" @click="handleLogout">
              <template #icon><icon-export /></template>
            </a-button>
          </a-tooltip>
        </div>
      </div>
    </a-layout-sider>

    <a-drawer
      :visible="mobileDrawer"
      placement="left"
      :width="240"
      :footer="false"
      class="mobile-drawer"
      @cancel="mobileDrawer = false"
    >
      <div class="sider-logo" @click="goHome">
        <svg width="28" height="28" viewBox="0 0 48 48" fill="none">
          <defs>
            <linearGradient id="drawer-g" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#165DFF" />
              <stop offset="100%" stop-color="#14C9C9" />
            </linearGradient>
          </defs>
          <rect width="48" height="48" rx="10" fill="url(#drawer-g)" />
          <text x="24" y="33" text-anchor="middle" font-size="22" font-weight="700" fill="#fff" font-family="system-ui">DB</text>
        </svg>
        <span class="logo-text">DB-Genius</span>
      </div>
      <a-menu
        :selected-keys="[currentPath]"
        @menu-item-click="handleMenuClick"
      >
        <a-menu-item v-for="item in menuItems" :key="item.key">
          <template #icon><component :is="item.icon" /></template>
          {{ item.label }}
        </a-menu-item>
      </a-menu>
      <div class="sider-footer">
        <a-divider :margin="12" />
        <div class="user-info">
          <a-avatar :size="28" :style="{ backgroundColor: '#165DFF' }">
            {{ userStore.nickname?.charAt(0) || userStore.username.charAt(0) }}
          </a-avatar>
          <span class="user-name">{{ userStore.nickname || userStore.username }}</span>
        </div>
        <div class="footer-actions">
          <a-tooltip :content="$t('admin.layout.collapseMenu')">
            <a-button size="small" @click="mobileDrawer = false">
              <template #icon><icon-shrink /></template>
            </a-button>
          </a-tooltip>
          <a-tooltip :content="$t('admin.layout.logout')">
            <a-button size="small" status="danger" @click="handleLogout">
              <template #icon><icon-export /></template>
            </a-button>
          </a-tooltip>
        </div>
      </div>
    </a-drawer>

    <a-layout class="main-layout">
      <a-layout-header class="admin-header mobile-only">
        <a-button type="text" @click="mobileDrawer = true">
          <template #icon><icon-menu :size="20" /></template>
        </a-button>
        <span class="header-title">DB-Genius</span>
        <LanguageSwitcher />
      </a-layout-header>
      <a-layout-content class="admin-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<style scoped lang="scss">
.admin-layout {
  height: calc(100vh - var(--banner-height, 0px));
}

.admin-sider {
  border-right: 1px solid var(--color-border-1);
  background: #fff;
}

.sider-logo {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid var(--color-border-1);
  cursor: pointer;

  &.collapsed {
    justify-content: center;
    padding: 0;
  }

  .logo-text {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-text-1);
    white-space: nowrap;
  }
}

.sider-footer {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 0 12px 12px;

  &.collapsed {
    .user-info {
      justify-content: center;
    }
  }
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;

  .user-name {
    flex: 1;
    font-size: 13px;
    color: var(--color-text-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;

  :deep(.arco-btn) {
    flex: 1;
  }

  &.collapsed-actions {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
  }
}

.main-layout {
  background: var(--color-bg-1);
}

.admin-header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  background: #fff;
  border-bottom: 1px solid var(--color-border-1);

  .header-title {
    font-size: 16px;
    font-weight: 600;
  }
}

.admin-content {
  overflow: hidden;
  background: var(--color-bg-1);
}

.desktop-sider {
  display: block;
}

.mobile-only {
  display: none;
}

@media (max-width: 992px) {
  .desktop-sider {
    display: none;
  }
  .mobile-only {
    display: flex;
  }
}
</style>
