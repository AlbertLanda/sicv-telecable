/* Shared navigation. Business actions and permissions stay server-rendered. */
(function () {
    'use strict';
    document.querySelectorAll('.table-responsive[role="region"]').forEach(function (region) {
        var hint = region.previousElementSibling;
        if (!hint || !hint.classList.contains('sicv-table-hint')) return;
        function updateOverflowHint() { hint.hidden = region.scrollWidth <= region.clientWidth + 1; }
        updateOverflowHint();
        if (window.ResizeObserver) new ResizeObserver(updateOverflowHint).observe(region);
        else window.addEventListener('resize', updateOverflowHint);
    });
    var filter = document.getElementById('sidebarFilter');
    if (filter) {
        var sections = Array.from(document.querySelectorAll('[data-sidebar-section]'));
        filter.addEventListener('input', function () {
            var term = filter.value.trim().toLocaleLowerCase('es');
            sections.forEach(function (section) {
                var matches = (section.dataset.sidebarSection || '').toLocaleLowerCase('es').includes(term);
                section.hidden = !!term && !matches;
                var panel = section.querySelector('.collapse');
                if (term && matches && panel) {
                    if (window.bootstrap) bootstrap.Collapse.getOrCreateInstance(panel, {toggle: false}).show();
                    else panel.classList.add('show');
                }
            });
        });
    }

    var toggle = document.getElementById('sidebarToggleBtn');
    var sidebar = document.getElementById('sicv-navigation');
    if (!toggle || !sidebar) return;
    var backdrop = document.getElementById('sidebarBackdrop');
    var main = document.getElementById('sicv-content');
    var media = window.matchMedia('(max-width: 991.98px)');
    var storageKey = 'sicv-sidebar-collapsed';
    var desktopCollapsed = false;
    try { desktopCollapsed = localStorage.getItem(storageKey) === '1'; } catch (e) {}

    function synchronize() {
        var open = media.matches ? document.body.classList.contains('sidebar-mobile-open') : !desktopCollapsed;
        document.body.classList.toggle('sidebar-collapsed', !media.matches && desktopCollapsed);
        toggle.setAttribute('aria-expanded', String(open));
        sidebar.inert = !open;
        if (main) main.inert = media.matches && open;
        if (backdrop) backdrop.hidden = !(media.matches && open);
    }
    function closeMobile() {
        if (!document.body.classList.contains('sidebar-mobile-open')) return;
        document.body.classList.remove('sidebar-mobile-open');
        synchronize();
        toggle.focus();
    }
    toggle.addEventListener('click', function () {
        if (media.matches) {
            var opening = !document.body.classList.contains('sidebar-mobile-open');
            document.body.classList.toggle('sidebar-mobile-open', opening);
            synchronize();
            if (opening) {
                var first = sidebar.querySelector('a, button, input');
                if (first) first.focus();
            }
        } else {
            desktopCollapsed = !desktopCollapsed;
            try { localStorage.setItem(storageKey, desktopCollapsed ? '1' : '0'); } catch (e) {}
            synchronize();
        }
    });
    if (backdrop) backdrop.addEventListener('click', closeMobile);
    document.addEventListener('keydown', function (event) {
        if (!media.matches || !document.body.classList.contains('sidebar-mobile-open')) return;
        if (event.key === 'Escape') { event.preventDefault(); closeMobile(); }
        if (event.key === 'Tab') {
            var controls = [toggle].concat(Array.from(sidebar.querySelectorAll('a[href], button, input'))
                .filter(function (element) { return !element.disabled && element.getClientRects().length; }));
            var index = controls.indexOf(document.activeElement);
            event.preventDefault();
            var next = index < 0 ? 0 : (index + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
            controls[next].focus();
        }
    });
    media.addEventListener('change', function () {
        var focusedSidebar = sidebar.contains(document.activeElement);
        document.body.classList.remove('sidebar-mobile-open');
        synchronize();
        if (sidebar.inert && focusedSidebar) toggle.focus();
    });
    synchronize();
})();
