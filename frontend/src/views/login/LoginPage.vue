<script setup lang="ts">
import { ref, reactive, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useUserStore } from '../../stores/user'
import { useTrialStore } from '../../stores/trial'
import GitHubIcon from '../../components/common/GitHubIcon.vue'
import LanguageSwitcher from '../../components/common/LanguageSwitcher.vue'
import { GITHUB_REPO_URL } from '../../config/site'
import { Message } from '@arco-design/web-vue'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const trialStore = useTrialStore()
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
})

onMounted(() => {
  trialStore.loadTrialStatus()
})

watch(
  () => trialStore.isTrial,
  (isTrial) => {
    if (isTrial) {
      form.username = 'admin'
      form.password = 'admin123'
    }
  },
  { immediate: true }
)

async function handleLogin() {
  if (!form.username || !form.password) {
    Message.warning(t('auth.fillCredentials'))
    return
  }
  loading.value = true
  try {
    await userStore.login(form)
    Message.success(t('auth.loginSuccess'))
    const redirect = (route.query.redirect as string) || '/admin/chat'
    router.push(redirect)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : ''
    Message.error(msg || t('auth.loginFailed'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-lang">
      <LanguageSwitcher />
    </div>
    <div class="login-card">
      <div class="login-header">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
          <defs>
            <linearGradient id="login-g" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#165DFF" />
              <stop offset="100%" stop-color="#14C9C9" />
            </linearGradient>
          </defs>
          <rect width="48" height="48" rx="10" fill="url(#login-g)" />
          <text x="24" y="33" text-anchor="middle" font-size="22" font-weight="700" fill="#fff" font-family="system-ui">DB</text>
        </svg>
        <h1>DB-Genius</h1>
        <p>{{ $t('auth.title') }}</p>
      </div>
      <div class="trial-alert" v-if="trialStore.isTrial">
        <icon-exclamation-circle />
        <div class="trial-alert__content">
          <div class="trial-alert__title">{{ $t('auth.trial.title') }}</div>
          <div class="trial-alert__desc">
            {{ $t('auth.trial.desc') }}
            <a v-if="GITHUB_REPO_URL" :href="GITHUB_REPO_URL" target="_blank">
              <GitHubIcon :size="12" /> {{ $t('auth.trial.sourceLink') }}
            </a>
          </div>
        </div>
      </div>

      <a-form :model="form" layout="vertical" @submit="handleLogin">
        <a-form-item :label="$t('auth.username')">
          <a-input
            v-model="form.username"
            :placeholder="$t('auth.usernamePlaceholder')"
            size="large"
            @keydown.enter="handleLogin"
          >
            <template #prefix><icon-user /></template>
          </a-input>
        </a-form-item>
        <a-form-item :label="$t('auth.password')">
          <a-input-password
            v-model="form.password"
            :placeholder="$t('auth.passwordPlaceholder')"
            size="large"
            @keydown.enter="handleLogin"
          >
            <template #prefix><icon-lock /></template>
          </a-input-password>
        </a-form-item>
        <a-form-item>
          <a-button
            type="primary"
            size="large"
            long
            :loading="loading"
            @click="handleLogin"
          >
            {{ $t('auth.loginButton') }}
          </a-button>
        </a-form-item>
      </a-form>
      <a-divider />
      <div class="login-footer">
        <router-link to="/">{{ $t('auth.backHome') }}</router-link>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #e8f0fe 0%, #f0f9ff 50%, #e8faf9 100%);
  padding: 24px;
}

.login-lang {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 10;
}

.login-card {
  width: 400px;
  padding: 40px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
}

.login-header {
  text-align: center;
  margin-bottom: 32px;

  svg {
    margin-bottom: 16px;
  }

  h1 {
    font-size: 24px;
    font-weight: 700;
    color: var(--color-text-1);
    margin-bottom: 4px;
  }

  p {
    font-size: 14px;
    color: var(--color-text-3);
  }
}

.login-footer {
  text-align: center;

  a {
    font-size: 13px;
    color: var(--color-text-3);
    &:hover {
      color: rgb(var(--primary-6));
    }
  }
}

.trial-alert {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 24px;
  border-radius: 8px;
  background: #fff7e6;
  border: 1px solid #ffd591;
  color: #d46b08;
  font-size: 13px;
  line-height: 1.5;

  svg {
    flex-shrink: 0;
    font-size: 18px;
    margin-top: 1px;
  }
}

.trial-alert__title {
  font-weight: 600;
  margin-bottom: 2px;
}

.trial-alert__desc {
  color: #ad5a00;

  a {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: rgb(var(--primary-6));
    text-decoration: underline;

    &:hover {
      color: rgb(var(--primary-7));
    }
  }
}

@media (max-width: 480px) {
  .login-card {
    width: 100%;
    padding: 28px 20px;
  }
}
</style>
