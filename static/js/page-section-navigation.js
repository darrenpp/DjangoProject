(function () {
    function onReady(callback) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', callback);
            return;
        }
        callback();
    }

    function getDocumentHeight() {
        const body = document.body || {};
        const html = document.documentElement || {};
        return Math.max(
            body.scrollHeight || 0,
            body.offsetHeight || 0,
            html.clientHeight || 0,
            html.scrollHeight || 0,
            html.offsetHeight || 0
        );
    }

    function getHeaderOffset() {
        const header = document.querySelector('.main-header, .app-header');
        if (!header) {
            return 18;
        }
        const style = window.getComputedStyle(header);
        const isFixed = style.position === 'fixed' || style.position === 'sticky';
        return isFixed ? header.getBoundingClientRect().height + 18 : 18;
    }

    function visibleElement(element) {
        if (!element || element.closest('.page-section-navigator, .helpdesk-widget, .app-loading-overlay, script, style')) {
            return false;
        }
        const rect = element.getBoundingClientRect();
        return rect.height > 32 && rect.width > 32;
    }

    function elementTop(element) {
        return element.getBoundingClientRect().top + window.pageYOffset;
    }

    function uniqueSortedSections(sections) {
        const seen = new Set();
        return sections
            .filter(visibleElement)
            .sort(function (a, b) {
                return elementTop(a) - elementTop(b);
            })
            .filter(function (element) {
                const key = Math.round(elementTop(element) / 24);
                if (seen.has(key)) {
                    return false;
                }
                seen.add(key);
                return true;
            });
    }

    function directSectionChildren(root) {
        if (!root) {
            return [];
        }
        return Array.from(root.children || []).filter(function (child) {
            return child.matches('.row, .card, section, article, div') && visibleElement(child);
        });
    }

    function collectSections() {
        const roots = Array.from(document.querySelectorAll(
            '[data-section-root], .content > .container-fluid, .portal-card, main, .content-wrapper'
        ));
        if (!roots.length) {
            roots.push(document.body);
        }

        let sections = [];
        roots.forEach(function (root) {
            sections = sections.concat(Array.from(root.querySelectorAll(
                '[data-section-nav-target], section[id], article[id], .row[id], .card[id], .portal-header, .portal-grid, .standards-strip, .official-info-section, .login-section'
            )));
        });

        if (sections.length < 2) {
            roots.forEach(function (root) {
                sections = sections.concat(directSectionChildren(root));
            });
        }

        return uniqueSortedSections(sections);
    }

    function scrollToPosition(position) {
        window.scrollTo({
            top: Math.max(0, position),
            behavior: 'smooth'
        });
    }

    function scrollToElement(element) {
        scrollToPosition(elementTop(element) - getHeaderOffset());
    }

    function currentSectionIndex(sections) {
        const marker = window.pageYOffset + getHeaderOffset() + 12;
        let index = 0;
        sections.forEach(function (section, sectionIndex) {
            if (elementTop(section) <= marker) {
                index = sectionIndex;
            }
        });
        return index;
    }

    onReady(function () {
        const navigator = document.querySelector('[data-page-section-navigator]');
        if (!navigator) {
            return;
        }

        const buttons = {
            top: navigator.querySelector('[data-page-scroll="top"]'),
            previous: navigator.querySelector('[data-page-scroll="previous"]'),
            next: navigator.querySelector('[data-page-scroll="next"]'),
            bottom: navigator.querySelector('[data-page-scroll="bottom"]')
        };

        let sections = collectSections();

        function refreshSections() {
            sections = collectSections();
            updateState();
        }

        function updateState() {
            const scrollable = getDocumentHeight() > window.innerHeight + 180;
            navigator.classList.toggle('is-hidden', !scrollable);
            if (!scrollable) {
                return;
            }

            const atTop = window.pageYOffset <= 24;
            const atBottom = window.pageYOffset + window.innerHeight >= getDocumentHeight() - 24;
            const index = currentSectionIndex(sections);
            if (buttons.top) {
                buttons.top.setAttribute('aria-disabled', atTop ? 'true' : 'false');
            }
            if (buttons.previous) {
                buttons.previous.disabled = atTop || index <= 0;
            }
            if (buttons.next) {
                buttons.next.disabled = atBottom || !sections.length || index >= sections.length - 1;
            }
            if (buttons.bottom) {
                buttons.bottom.disabled = atBottom;
            }
        }

        function move(direction) {
            if (direction === 'top') {
                scrollToPosition(0);
                return;
            }
            if (direction === 'bottom') {
                scrollToPosition(getDocumentHeight());
                return;
            }
            if (!sections.length) {
                return;
            }

            const index = currentSectionIndex(sections);
            const targetIndex = direction === 'previous'
                ? Math.max(0, index - 1)
                : Math.min(sections.length - 1, index + 1);
            scrollToElement(sections[targetIndex]);
        }

        navigator.addEventListener('click', function (event) {
            const control = event.target.closest('[data-page-scroll]');
            if (!control) {
                return;
            }
            event.preventDefault();
            if (control.disabled || control.getAttribute('aria-disabled') === 'true') {
                return;
            }
            move(control.getAttribute('data-page-scroll'));
        });

        let ticking = false;
        window.addEventListener('scroll', function () {
            if (ticking) {
                return;
            }
            ticking = true;
            window.requestAnimationFrame(function () {
                updateState();
                ticking = false;
            });
        }, { passive: true });

        window.addEventListener('resize', refreshSections);
        window.setTimeout(refreshSections, 250);
        window.setTimeout(refreshSections, 1200);
        updateState();
    });
})();
