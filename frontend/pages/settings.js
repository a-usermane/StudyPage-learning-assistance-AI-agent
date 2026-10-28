import {$} from '../shared/dom.js';

const sections = ['general', 'prompts'];

export function installSettingsNavigation() {
  for (const name of sections) {
    $('settings-tab-' + name).onkeydown = event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const target = event.key === 'Home' ? 'general' : event.key === 'End' ? 'prompts'
        : sections[(sections.indexOf(name) + 1) % sections.length];
      const tab = $('settings-tab-' + target);
      tab.focus(); location.hash = tab.hash;
    };
  }
}

export function showSettings(name = 'general') {
  const page = $('settings-page');
  if (page.dataset.section !== name) page.scrollTop = 0;
  page.dataset.section = name;
  for (const section of sections) {
    const selected = section === name;
    $('settings-' + section).hidden = !selected;
    const tab = $('settings-tab-' + section);
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  }
}
