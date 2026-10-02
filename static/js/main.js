/**
 * Athenaeum Ikedi - Client-side interactive enhancements.
 * Pure Vanilla JS, zero dependencies, CSP compliant.
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Mobile Navigation Toggle
  const navToggle = document.getElementById('nav-toggle');
  const siteNav = document.getElementById('site-nav');

  if (navToggle && siteNav) {
    function setNavState(isOpen) {
      navToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      siteNav.classList.toggle('site-nav--open', isOpen);
    }

    navToggle.addEventListener('click', () => {
      const isExpanded = navToggle.getAttribute('aria-expanded') === 'true';
      setNavState(!isExpanded);
    });

    // Close on click outside
    document.addEventListener('click', (event) => {
      if (siteNav.classList.contains('site-nav--open') &&
          !siteNav.contains(event.target) &&
          !navToggle.contains(event.target)) {
        setNavState(false);
      }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && siteNav.classList.contains('site-nav--open')) {
        setNavState(false);
      }
    });
  }

  // 2. Flash Messages auto-dismiss & close button
  const messageItems = document.querySelectorAll('.messages .message');
  messageItems.forEach((msg) => {
    // Add close button
    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'message__close';
    closeBtn.setAttribute('aria-label', 'Dismiss alert');
    closeBtn.innerHTML = '&times;';
    closeBtn.addEventListener('click', () => {
      dismissMessage(msg);
    });
    msg.appendChild(closeBtn);

    // Auto dismiss after 6 seconds for success/info
    if (msg.classList.contains('message--success') || msg.classList.contains('message--info')) {
      setTimeout(() => {
        dismissMessage(msg);
      }, 6000);
    }
  });

  function dismissMessage(el) {
    el.style.transition = 'opacity 0.3s ease, transform 0.3s ease, max-height 0.3s ease';
    el.style.opacity = '0';
    el.style.transform = 'translateY(-8px)';
    setTimeout(() => {
      el.remove();
    }, 300);
  }

  // 3. Confirm dialogs for destructive actions
  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (e) => {
      const confirmText = form.getAttribute('data-confirm');
      if (!window.confirm(confirmText)) {
        e.preventDefault();
      }
    });
  });

  // ================================================================
  // 4. Theme Engine - Dark Mode Support
  // ================================================================

  const htmlEl = document.documentElement;
  const storedTheme = htmlEl.getAttribute('data-theme') || 'light';

  /**
   * Apply the resolved theme ('light' or 'dark') to the HTML element.
   * Adds a brief transition class for smooth colour changes.
   */
  function applyResolvedTheme(resolved) {
    htmlEl.classList.add('theme-transition');
    htmlEl.setAttribute('data-theme', resolved);
    // Remove transition class after animation completes
    setTimeout(() => {
      htmlEl.classList.remove('theme-transition');
    }, 350);
  }

  /**
   * Resolve 'system' to the OS preference ('light' or 'dark').
   */
  function getSystemTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  // If the server sent 'system', resolve it immediately to avoid
  // a flash of the wrong theme between first paint and JS execution.
  if (storedTheme === 'system') {
    const resolved = getSystemTheme();
    htmlEl.setAttribute('data-theme', resolved);
  }

  // Listen for OS theme changes when the preference is 'system'.
  // We track the original preference separately from the resolved value.
  let currentPreference = storedTheme;
  const darkMediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

  function onSystemThemeChange(e) {
    if (currentPreference === 'system') {
      applyResolvedTheme(e.matches ? 'dark' : 'light');
    }
  }

  if (darkMediaQuery.addEventListener) {
    darkMediaQuery.addEventListener('change', onSystemThemeChange);
  } else if (darkMediaQuery.addListener) {
    // Safari < 14 fallback
    darkMediaQuery.addListener(onSystemThemeChange);
  }

  // ----------------------------------------------------------------
  // Settings page: Live theme preview when clicking radio cards
  // ----------------------------------------------------------------

  const themeRadios = document.querySelectorAll('input[name="theme"]');
  if (themeRadios.length > 0) {
    themeRadios.forEach((radio) => {
      radio.addEventListener('change', () => {
        const selectedTheme = radio.value;
        currentPreference = selectedTheme;

        if (selectedTheme === 'system') {
          applyResolvedTheme(getSystemTheme());
        } else {
          applyResolvedTheme(selectedTheme);
        }

        // Update visual selection state on theme cards
        document.querySelectorAll('.theme-card').forEach((card) => {
          card.classList.remove('theme-card--selected');
        });
        const parentCard = radio.closest('.theme-card');
        if (parentCard) {
          parentCard.classList.add('theme-card--selected');
        }
      });
    });
  }

  // Similarly, handle radio card selection highlighting
  const radioCards = document.querySelectorAll('.radio-card input[type="radio"]');
  radioCards.forEach((radio) => {
    radio.addEventListener('change', () => {
      const groupName = radio.getAttribute('name');
      document.querySelectorAll(`.radio-card input[name="${groupName}"]`).forEach((r) => {
        const card = r.closest('.radio-card');
        if (card) card.classList.toggle('radio-card--selected', r.checked);
      });
    });
  });
});
