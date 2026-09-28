<script setup lang="ts">
import { useRouter } from 'vue-router'
import GitHubIcon from '../common/GitHubIcon.vue'
import { GITHUB_REPO_URL } from '../../config/site'

const router = useRouter()
const year = new Date().getFullYear()
</script>

<template>
  <footer class="footer">
    <div class="footer-inner">
      <div class="footer-grid">
        <div class="footer-brand">
          <div class="brand-row">
            <svg width="28" height="28" viewBox="0 0 48 48" fill="none" aria-hidden="true">
              <defs>
                <linearGradient id="footer-g" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#165DFF" />
                  <stop offset="100%" stop-color="#14C9C9" />
                </linearGradient>
              </defs>
              <rect width="48" height="48" rx="10" fill="url(#footer-g)" />
              <text x="24" y="33" text-anchor="middle" font-size="22" font-weight="700" fill="#fff" font-family="system-ui">DB</text>
            </svg>
            <span>DB-Genius</span>
          </div>
          <p class="brand-desc">{{ $t('landing.footer.brandDesc') }}</p>
        </div>
        <nav class="footer-col" :aria-label="$t('landing.footer.productNav')">
          <h3>{{ $t('landing.footer.product') }}</h3>
          <a href="#features">{{ $t('landing.footer.features') }}</a>
          <a href="#showcase">{{ $t('landing.footer.showcase') }}</a>
          <a href="#how-it-works">{{ $t('landing.footer.howItWorks') }}</a>
          <a href="#faq">{{ $t('landing.footer.faq') }}</a>
        </nav>
        <nav class="footer-col" :aria-label="$t('landing.footer.supportNav')">
          <h3>{{ $t('landing.footer.support') }}</h3>
          <a v-if="GITHUB_REPO_URL" :href="GITHUB_REPO_URL" target="_blank" class="github-link">
            <GitHubIcon :size="13" /> GitHub
          </a>
          <a href="/login" @click.prevent="router.push('/login')">{{ $t('landing.footer.login') }}</a>
        </nav>
      </div>
      <div class="footer-bottom">
        <p>
          © {{ year }} DB-Genius. {{ $t('landing.footer.tagline') }}
          <a class="beian-link" href="https://beian.miit.gov.cn" target="_blank" rel="nofollow noopener">鄂ICP备2022018360号-5</a>
        </p>
      </div>
    </div>
  </footer>
</template>

<style scoped lang="scss">
.footer {
  padding: 56px 24px 32px;
  border-top: 1px solid var(--color-border-1);
  background: #fff;
}

.footer-inner {
  max-width: 1200px;
  margin: 0 auto;
}

.footer-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 48px;
  padding-bottom: 40px;
}

.footer-brand {
  .brand-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 16px;
    font-weight: 700;
    color: var(--color-text-1);
    margin-bottom: 12px;
  }

  .brand-desc {
    font-size: 13px;
    line-height: 1.8;
    color: var(--color-text-4);
    max-width: 320px;
  }
}

.footer-col {
  display: flex;
  flex-direction: column;
  gap: 12px;

  h3 {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-text-1);
    margin-bottom: 4px;
  }

  a {
    font-size: 13px;
    color: var(--color-text-3);
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

.footer-bottom {
  padding-top: 24px;
  border-top: 1px solid var(--color-border-1);

  p {
    font-size: 13px;
    color: var(--color-text-4);
    text-align: center;
  }

  .beian-link {
    font-size: 13px;
    color: var(--color-text-4);
    margin-left: 8px;
    transition: color 0.2s;

    &:hover {
      color: rgb(var(--primary-6));
    }
  }
}

@media (max-width: 768px) {
  .footer-grid {
    grid-template-columns: 1fr;
    gap: 32px;
    text-align: center;
  }

  .footer-brand {
    .brand-row {
      justify-content: center;
    }

    .brand-desc {
      margin: 0 auto;
    }
  }
}
</style>
