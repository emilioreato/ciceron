const test = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '..', 'extension', 'content.js'), 'utf8');

function setup(withNavigation) {
  const classes = new Set();
  const handlers = {};
  const intervals = new Map();
  const timeouts = [];
  const styles = new Map();
  let storageChanged;
  const listen = (event, fn) => { handlers[event] = fn; };
  const document = {
    body: null,
    hidden: false,
    documentElement: {
      classList: {
        add: value => classes.add(value),
        remove: (...values) => values.forEach(value => classes.delete(value)),
        toggle: (value, active) => active ? classes.add(value) : classes.delete(value),
      },
      appendChild: style => styles.set(style.id, style),
    },
    addEventListener: listen,
    createElement: () => ({}),
    getElementById: id => styles.get(id),
  };
  const location = new URL('https://www.youtube.com/results?search_query=ciceron');
  vm.runInNewContext(source, {
    URL, location, document, sessionStorage: { getItem: () => null },
    window: { addEventListener: listen, navigation: withNavigation
      ? { addEventListener: listen, oncurrententrychange: null } : undefined },
    chrome: { storage: { local: { get: (_, fn) => fn({ ciceron_enabled: true }) },
      onChanged: { addListener: fn => { storageChanged = fn; } } } },
    setInterval: fn => { intervals.set(fn, fn); return fn; },
    clearInterval: id => intervals.delete(id),
    setTimeout: fn => timeouts.push(fn),
  });
  return { classes, handlers, intervals, timeouts, location, document, storageChanged };
}

test('Chromium aplica un cambio de ruta sin un temporizador periódico', () => {
  const context = setup(true);
  assert.equal(context.intervals.size, 0);
  assert(context.classes.has('pf-youtube-search'));
  context.location.pathname = '/feed/subscriptions';
  context.handlers.currententrychange();
  context.handlers['yt-navigate-finish']();
  assert.equal(context.timeouts.length, 1);
  context.timeouts.shift()();
  assert(context.classes.has('pf-blocked'));
  context.storageChanged({ ciceron_enabled: { newValue: false } }, 'local');
  assert(!context.classes.has('pf-blocked'));
});

test('La comprobación de respaldo duerme con la pestaña oculta o con Pausa Feed desactivado', () => {
  const context = setup(false);
  assert.equal(context.intervals.size, 1);
  context.document.hidden = true;
  context.handlers.visibilitychange();
  assert.equal(context.intervals.size, 0);
  context.location.pathname = '/feed/subscriptions';
  context.document.hidden = false;
  context.handlers.visibilitychange();
  context.timeouts.shift()();
  assert(context.classes.has('pf-blocked'));
  context.storageChanged({ ciceron_enabled: { newValue: false } }, 'local');
  assert.equal(context.intervals.size, 0);
});
