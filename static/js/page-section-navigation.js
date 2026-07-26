(function () {
    if ('scrollRestoration' in window.history) {
        window.history.scrollRestoration = 'manual';
    }

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

    function getScrollElement() {
        return document.scrollingElement || document.documentElement || document.body;
    }

    function getScrollTop() {
        const scrollElement = getScrollElement();
        return window.pageYOffset || scrollElement.scrollTop || document.body.scrollTop || 0;
    }

    function applyScrollTop(position, behavior) {
        const top = Math.max(0, position);
        const options = { top: top, left: 0, behavior: behavior || 'smooth' };
        const scrollElement = getScrollElement();

        try {
            window.scrollTo(options);
        } catch (error) {
            window.scrollTo(0, top);
        }

        if (scrollElement && scrollElement !== document.body) {
            try {
                scrollElement.scrollTo(options);
            } catch (error) {
                scrollElement.scrollTop = top;
            }
        }
        document.body.scrollTop = top;
    }

    function shouldResetScrollOnLoad() {
        if (window.location.hash) {
            return false;
        }
        const perf = window.performance;
        const entries = perf && perf.getEntriesByType
            ? perf.getEntriesByType('navigation')
            : [];
        if (entries.length && entries[0].type) {
            return entries[0].type === 'reload';
        }
        return !!(perf && perf.navigation && perf.navigation.type === 1);
    }

    function resetScrollAfterReload() {
        if (!shouldResetScrollOnLoad()) {
            return;
        }
        [0, 50, 250, 800].forEach(function (delay) {
            window.setTimeout(function () {
                applyScrollTop(0, 'auto');
            }, delay);
        });
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
        return element.getBoundingClientRect().top + getScrollTop();
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
            return child.matches([
                '[data-section-nav-target]',
                '.row',
                '.card',
                'section',
                'article',
                '.page-toolbar',
                '.platform-standards-bar',
                '.portal-header',
                '.portal-grid',
                '.standards-strip',
                '.official-info-section',
                '.login-section'
            ].join(', ')) && visibleElement(child);
        });
    }

    function collectSections() {
        let roots = Array.from(document.querySelectorAll(
            '[data-section-root], .content > .container-fluid, .portal-card, main'
        ));
        if (!roots.length) {
            roots = Array.from(document.querySelectorAll('.content-wrapper'));
        }
        if (!roots.length && document.body) {
            roots.push(document.body);
        }

        let sections = [];
        roots.forEach(function (root) {
            sections = sections.concat(directSectionChildren(root));
            sections = sections.concat(Array.from(root.querySelectorAll(
                [
                    '[data-section-nav-target]',
                    'section[id]',
                    'article[id]',
                    '.row[id]',
                    '.card[id]',
                    '.platform-standards-bar',
                    '.portal-header',
                    '.portal-grid',
                    '.standards-strip',
                    '.official-info-section',
                    '.login-section'
                ].join(', ')
            )));
        });

        if (sections.length < 2) {
            sections = sections.concat(Array.from(document.querySelectorAll(
                '.content-wrapper > section, .content > .container-fluid > .row, .content > .container-fluid > .card'
            )));
        }

        return uniqueSortedSections(sections);
    }

    function scrollToPosition(position) {
        const target = Math.max(0, position);
        applyScrollTop(target, 'smooth');
        window.setTimeout(function () {
            if (Math.abs(getScrollTop() - target) > 24) {
                applyScrollTop(target, 'auto');
            }
        }, 450);
    }

    function scrollToElement(element) {
        scrollToPosition(elementTop(element) - getHeaderOffset());
    }

    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    function currentSectionIndex(sections) {
        const marker = getScrollTop() + getHeaderOffset() + 12;
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
        resetScrollAfterReload();

        const buttons = {
            top: navigator.querySelector('[data-page-scroll="top"]'),
            previous: navigator.querySelector('[data-page-scroll="previous"]'),
            next: navigator.querySelector('[data-page-scroll="next"]'),
            bottom: navigator.querySelector('[data-page-scroll="bottom"]')
        };
        const dragHandle = navigator.querySelector('[data-page-section-drag-handle]');
        const dragSurface = dragHandle || navigator;

        let sections = collectSections();
        let savedPositionApplied = false;
        let navigatorDragStarted = false;
        let navigatorPointerActive = false;
        let navigatorOffsetX = 0;
        let navigatorOffsetY = 0;
        let navigatorStartX = 0;
        let navigatorStartY = 0;
        const navigatorStorageKey = 'ndohPageSectionNavigatorPosition';
        const navigatorDragThreshold = 8;

        function applyNavigatorPosition(left, top) {
            const rect = navigator.getBoundingClientRect();
            const width = rect.width || navigator.offsetWidth || 260;
            const height = rect.height || navigator.offsetHeight || 48;
            const maxLeft = window.innerWidth - width - 8;
            const maxTop = window.innerHeight - height - 8;
            const nextLeft = clamp(left, 8, Math.max(8, maxLeft));
            const nextTop = clamp(top, 8, Math.max(8, maxTop));
            navigator.style.left = nextLeft + 'px';
            navigator.style.top = nextTop + 'px';
            navigator.style.right = 'auto';
            navigator.style.bottom = 'auto';
        }

        function applySavedNavigatorPosition() {
            if (savedPositionApplied || navigator.classList.contains('is-hidden')) {
                return;
            }
            savedPositionApplied = true;
            try {
                localStorage.removeItem(navigatorStorageKey);
            } catch (error) {
                return;
            }
        }

        function saveNavigatorPosition() {
            try {
                localStorage.removeItem(navigatorStorageKey);
            } catch (error) {
                return;
            }
        }

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
            applySavedNavigatorPosition();

            const scrollTop = getScrollTop();
            const atTop = scrollTop <= 24;
            const atBottom = scrollTop + window.innerHeight >= getDocumentHeight() - 24;
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

        dragSurface.addEventListener('pointerdown', function (event) {
            if (event.button && event.button !== 0) {
                return;
            }
            if (!event.target.closest('[data-page-section-drag-handle]') && event.target.closest('[data-page-scroll]')) {
                return;
            }
            event.preventDefault();
            navigatorPointerActive = true;
            navigatorDragStarted = false;
            navigatorStartX = event.clientX;
            navigatorStartY = event.clientY;
            const rect = navigator.getBoundingClientRect();
            navigatorOffsetX = event.clientX - rect.left;
            navigatorOffsetY = event.clientY - rect.top;
            dragSurface.setPointerCapture(event.pointerId);
        });

        dragSurface.addEventListener('pointermove', function (event) {
            if (!navigatorPointerActive) {
                return;
            }
            const movedX = Math.abs(event.clientX - navigatorStartX);
            const movedY = Math.abs(event.clientY - navigatorStartY);
            if (!navigatorDragStarted && movedX < navigatorDragThreshold && movedY < navigatorDragThreshold) {
                return;
            }
            navigatorDragStarted = true;
            navigator.classList.add('is-dragging');
            applyNavigatorPosition(event.clientX - navigatorOffsetX, event.clientY - navigatorOffsetY);
        });

        function finishNavigatorDrag(event) {
            if (!navigatorPointerActive) {
                return;
            }
            navigatorPointerActive = false;
            navigator.classList.remove('is-dragging');
            if (event && dragSurface.hasPointerCapture && dragSurface.hasPointerCapture(event.pointerId)) {
                dragSurface.releasePointerCapture(event.pointerId);
            }
            if (navigatorDragStarted) {
                saveNavigatorPosition();
            }
            window.setTimeout(function () {
                navigatorDragStarted = false;
            }, 0);
        }

        dragSurface.addEventListener('pointerup', finishNavigatorDrag);
        dragSurface.addEventListener('pointercancel', finishNavigatorDrag);

        navigator.addEventListener('click', function (event) {
            if (navigatorDragStarted) {
                event.preventDefault();
                event.stopPropagation();
            }
        }, true);

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

        window.addEventListener('resize', function () {
            refreshSections();
            if (!navigator.classList.contains('is-hidden')) {
                const rect = navigator.getBoundingClientRect();
                applyNavigatorPosition(rect.left, rect.top);
                if (savedPositionApplied) {
                    saveNavigatorPosition();
                }
            }
        });
        window.setTimeout(refreshSections, 250);
        window.setTimeout(refreshSections, 1200);
        updateState();
    });
})();
