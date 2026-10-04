// Local SVG paths keep navigation consistent across system fonts.
const paths = {
  'home-button': '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/>',
  'plugins-button': '<path d="M9 3h6v5h5v6h-5v7H9v-7H4V8h5Z"/><path d="M9 8h6"/>',
  'menu-button': '<path d="M4 6h16M4 12h16M4 18h16"/>',
  'settings-button': '<path d="m9 3-.6 2.4-2.1 1.2L4 6l-2 3.5 1.8 1.7v2.4L2 15.3l2 3.5 2.3-.6 2.1 1.2L9 22h6l.6-2.6 2.1-1.2 2.3.6 2-3.5-1.8-1.7v-2.4L22 9.5 20 6l-2.3.6-2.1-1.2L15 3Z"/><circle cx="12" cy="12.5" r="3"/>'
};
export function installNavigationIcons() {
  for (const [id, path] of Object.entries(paths)) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    // Only these authored, fixed paths are inserted; user content never reaches innerHTML.
    svg.innerHTML = path;
    document.getElementById(id).replaceChildren(svg);
  }
}
