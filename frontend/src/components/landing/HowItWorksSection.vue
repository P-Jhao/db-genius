<template>
  <section id="how-it-works" class="how-it-works">
    <div class="how-inner">
      <div class="section-header">
        <h2>{{ $t('landing.howItWorks.title') }}</h2>
        <p>{{ $t('landing.howItWorks.subtitle') }}</p>
      </div>
      <div class="steps">
        <div class="step">
          <div class="step-number">1</div>
          <div class="step-content">
            <h3>{{ $t('landing.howItWorks.steps.step1.title') }}</h3>
            <p>{{ $t('landing.howItWorks.steps.step1.desc') }}</p>
          </div>
          <div class="step-illustration">
            <svg viewBox="0 0 200 120" fill="none">
              <rect x="10" y="10" width="180" height="100" rx="8" fill="#F2F3F5"/>
              <rect x="24" y="28" width="60" height="8" rx="3" fill="#C9CDD4"/>
              <rect x="100" y="28" width="80" height="8" rx="3" fill="#E5E6EB"/>
              <rect x="24" y="48" width="60" height="8" rx="3" fill="#C9CDD4"/>
              <rect x="100" y="48" width="80" height="8" rx="3" fill="#E5E6EB"/>
              <rect x="24" y="68" width="60" height="8" rx="3" fill="#C9CDD4"/>
              <rect x="100" y="68" width="80" height="8" rx="3" fill="#E5E6EB"/>
              <circle cx="160" cy="92" r="10" fill="#00B42A"/>
              <path d="M155 92l3 3 6-6" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </div>
        </div>
        <div class="step-connector" />
        <div class="step">
          <div class="step-number">2</div>
          <div class="step-content">
            <h3>{{ $t('landing.howItWorks.steps.step2.title') }}</h3>
            <p>{{ $t('landing.howItWorks.steps.step2.desc') }}</p>
          </div>
          <div class="step-illustration">
            <svg viewBox="0 0 200 120" fill="none">
              <rect x="10" y="10" width="180" height="100" rx="8" fill="#F2F3F5"/>
              <rect x="24" y="24" width="100" height="28" rx="8" fill="#E8F3FF"/>
              <rect x="32" y="34" width="76" height="8" rx="3" fill="#165DFF" opacity="0.5"/>
              <rect x="60" y="62" width="120" height="28" rx="8" fill="#fff"/>
              <rect x="68" y="72" width="96" height="8" rx="3" fill="#4E5969"/>
            </svg>
          </div>
        </div>
        <div class="step-connector" />
        <div class="step">
          <div class="step-number">3</div>
          <div class="step-content">
            <h3>{{ $t('landing.howItWorks.steps.step3.title') }}</h3>
            <p>{{ $t('landing.howItWorks.steps.step3.desc') }}</p>
          </div>
          <div class="step-illustration">
            <svg viewBox="0 0 200 120" fill="none">
              <rect x="10" y="10" width="180" height="100" rx="8" fill="#F2F3F5"/>
              <rect x="24" y="24" width="152" height="14" rx="4" fill="#E5E6EB"/>
              <rect x="24" y="24" width="100" height="14" rx="4" fill="#165DFF" opacity="0.3"/>
              <rect x="24" y="46" width="152" height="8" rx="3" fill="#C9CDD4"/>
              <rect x="24" y="62" width="120" height="8" rx="3" fill="#C9CDD4"/>
              <rect x="24" y="78" width="140" height="8" rx="3" fill="#C9CDD4"/>
              <rect x="24" y="94" width="80" height="8" rx="3" fill="#00B42A" opacity="0.3"/>
            </svg>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped lang="scss">
.how-it-works {
  padding: 80px 24px;
  background: #f7f8fa;
}

.how-inner {
  max-width: 1200px;
  margin: 0 auto;
}

.section-header {
  text-align: center;
  margin-bottom: 48px;

  h2 {
    font-size: 32px;
    font-weight: 700;
    color: var(--color-text-1);
    margin-bottom: 8px;
  }

  p {
    font-size: 16px;
    color: var(--color-text-3);
  }
}

.steps {
  display: flex;
  align-items: flex-start;
  gap: 0;
}

.step {
  flex: 1;
  min-width: 0;
  text-align: center;
  padding: 0 16px;
  display: flex;
  flex-direction: column;
  align-items: center;

  .step-number {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: linear-gradient(135deg, #165DFF, #14C9C9);
    color: #fff;
    font-size: 18px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 16px;
  }

  .step-content {
    h3 {
      font-size: 18px;
      font-weight: 600;
      margin-bottom: 8px;
      color: var(--color-text-1);
    }

    p {
      font-size: 14px;
      color: var(--color-text-3);
      line-height: 1.6;
      margin-bottom: 20px;
    }
  }

  .step-illustration {
    width: 100%;
    display: flex;
    justify-content: center;

    svg {
      display: block;
      width: 100%;
      max-width: 200px;
      height: auto;
    }
  }
}

.step-connector {
  width: 40px;
  height: 2px;
  background: var(--color-border-2);
  margin-top: 20px;
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .how-it-works {
    padding: 56px 20px;
  }

  .steps {
    flex-direction: column;
    gap: 32px;
    align-items: stretch;
  }

  .step {
    width: 100%;
    padding: 0;
  }

  .step-connector {
    width: 2px;
    height: 24px;
    margin: 0;
    align-self: center;
  }
}
</style>
