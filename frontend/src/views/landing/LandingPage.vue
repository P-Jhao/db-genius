<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTrialStore } from '../../stores/trial'
import { GITHUB_REPO_URL } from '../../config/site'
import GitHubIcon from '../../components/common/GitHubIcon.vue'
import LanguageSwitcher from '../../components/common/LanguageSwitcher.vue'
import HeroSection from '../../components/landing/HeroSection.vue'
import FeatureSection from '../../components/landing/FeatureSection.vue'
import DatabaseSection from '../../components/landing/DatabaseSection.vue'
import ShowcaseSection from '../../components/landing/ShowcaseSection.vue'
import HowItWorksSection from '../../components/landing/HowItWorksSection.vue'
import FaqSection from '../../components/landing/FaqSection.vue'
import CtaSection from '../../components/landing/CtaSection.vue'
import FooterSection from '../../components/landing/FooterSection.vue'

const router = useRouter()
const trialStore = useTrialStore()
const mobileMenuOpen = ref(false)

onMounted(() => {
  trialStore.loadTrialStatus()
})

function goLogin() {
  router.push('/login')
}

function goTrial() {
  router.push('/admin/chat')
}
</script>

<template>
  <div class="landing-page">
    <header class="landing-header">
      <div class="header-inner">
        <div class="logo" @click="router.push('/')">
          <svg width="32" height="32" viewBox="0 0 48 48" fill="none" aria-hidden="true">
            <defs>
              <linearGradient id="logo-g" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#165DFF" />
                <stop offset="100%" stop-color="#14C9C9" />
              </linearGradient>
            </defs>
            <rect width="48" height="48" rx="10" fill="url(#logo-g)" />
            <text x="24" y="33" text-anchor="middle" font-size="22" font-weight="700" fill="#fff" font-family="system-ui">DB</text>
          </svg>
          <span class="logo-text">DB-Genius</span>
        </div>
        <nav class="header-nav desktop-only" :aria-label="$t('landing.nav.mainNav')">
          <a href="#features">{{ $t('landing.nav.features') }}</a>
          <a href="#databases">{{ $t('landing.nav.databases') }}</a>
          <a href="#showcase">{{ $t('landing.nav.showcase') }}</a>
          <a href="#how-it-works">{{ $t('landing.nav.howItWorks') }}</a>
          <a href="#faq">{{ $t('landing.nav.faq') }}</a>
          <a v-if="GITHUB_REPO_URL" :href="GITHUB_REPO_URL" target="_blank" class="github-link">
            <GitHubIcon :size="14" /> GitHub
          </a>
        </nav>
        <div class="header-actions desktop-only">
          <LanguageSwitcher />
          <a-button v-if="!trialStore.isTrial" type="text" @click="goLogin">{{ $t('landing.nav.login') }}</a-button>
          <a-button type="primary" @click="trialStore.isTrial ? goTrial() : goLogin()">
            {{ trialStore.isTrial ? $t('landing.nav.tryOpenSource') : $t('landing.nav.freeTrial') }}
          </a-button>
        </div>
        <div class="mobile-only mobile-header-actions">
          <LanguageSwitcher />
          <a-button type="text" :aria-label="$t('landing.nav.openMenu')" @click="mobileMenuOpen = !mobileMenuOpen">
            <template #icon>
              <icon-menu />
            </template>
          </a-button>
        </div>
      </div>
      <a-drawer
        :visible="mobileMenuOpen"
        placement="right"
        :width="280"
        :footer="false"
        @cancel="mobileMenuOpen = false"
      >
        <div class="mobile-menu">
          <a href="#features" @click="mobileMenuOpen = false">{{ $t('landing.nav.features') }}</a>
          <a href="#databases" @click="mobileMenuOpen = false">{{ $t('landing.nav.databases') }}</a>
          <a href="#showcase" @click="mobileMenuOpen = false">{{ $t('landing.nav.showcase') }}</a>
          <a href="#how-it-works" @click="mobileMenuOpen = false">{{ $t('landing.nav.howItWorks') }}</a>
          <a href="#faq" @click="mobileMenuOpen = false">{{ $t('landing.nav.faq') }}</a>
          <a v-if="GITHUB_REPO_URL" :href="GITHUB_REPO_URL" target="_blank" class="github-link">
            <GitHubIcon :size="16" /> GitHub
          </a>
          <a-button v-if="trialStore.isTrial" type="primary" long @click="goTrial(); mobileMenuOpen = false">
            {{ $t('landing.nav.tryOpenSource') }}
          </a-button>
          <template v-else>
            <a-button type="primary" long @click="goLogin(); mobileMenuOpen = false">{{ $t('landing.nav.freeTrial') }}</a-button>
            <a-button long @click="goLogin(); mobileMenuOpen = false">{{ $t('landing.nav.login') }}</a-button>
          </template>
          <div class="mobile-menu-lang">
            <LanguageSwitcher />
          </div>
        </div>
      </a-drawer>
    </header>

    <main>
      <HeroSection @cta="trialStore.isTrial ? goTrial() : goLogin()" />
      <FeatureSection />
      <DatabaseSection />
      <ShowcaseSection />
      <HowItWorksSection />
      <FaqSection />
      <CtaSection @cta="trialStore.isTrial ? goTrial() : goLogin()" />
    </main>

    <FooterSection />
  </div>
</template>

<style scoped lang="scss">
.landing-page {
  min-height: 100vh;
  background: #fafbfc;
  overflow-x: hidden;
}

.landing-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--color-border-1);
}

.header-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;

  .logo-text {
    font-size: 20px;
    font-weight: 700;
    color: var(--color-text-1);
  }
}

.header-nav {
  display: flex;
  gap: 28px;

  a {
    font-size: 14px;
    color: var(--color-text-2);
    transition: color 0.2s;
    &:hover {
      color: rgb(var(--primary-6));
    }
  }
}

.github-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mobile-header-actions {
  align-items: center;
  gap: 4px;
}

.mobile-menu {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-top: 16px;

  a {
    font-size: 16px;
    color: var(--color-text-1);
    padding: 8px 0;
  }
}

.mobile-menu-lang {
  padding-top: 8px;
  border-top: 1px solid var(--color-border-1);
}

.desktop-only {
  display: flex;
}

.mobile-only {
  display: none;
}

@media (max-width: 900px) {
  .desktop-only {
    display: none !important;
  }
  .mobile-only {
    display: flex;
  }
}
</style>
