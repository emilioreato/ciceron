const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const extension = path.join(__dirname, '..', 'extension');
const run = (name, context) =>
  vm.runInContext(fs.readFileSync(path.join(extension, name), 'utf8'), context);
const flush = () => new Promise(resolve => setImmediate(resolve));

function setup() {
  const local = {};
  const listeners = [];
  const alarms = [];
  const ports = [];
  let rulesEnabled;
  const chrome = {
    storage: {
      local: {
        get: async defaults => ({ ...defaults, ...local }),
        set: async values => {
          const changes = {};
          for (const [key, value] of Object.entries(values)) {
            if (JSON.stringify(local[key]) === JSON.stringify(value)) continue;
            changes[key] = { oldValue: local[key], newValue: value };
            local[key] = value;
          }
          if (Object.keys(changes).length) emit(changes, 'local');
        },
      },
      onChanged: { addListener: listener => listeners.push(listener) },
    },
    declarativeNetRequest: {
      updateEnabledRulesets: async ({ enableRulesetIds }) => {
        rulesEnabled = enableRulesetIds.includes('hard_block');
      },
    },
    alarms: { create() {}, onAlarm: { addListener: listener => alarms.push(listener) } },
    runtime: {
      onInstalled: { addListener() {} },
      onStartup: { addListener() {} },
      connectNative() {
        const port = {
          sent: [],
          onMessage: { addListener(listener) { port.message = listener; } },
          onDisconnect: { addListener(listener) { port.disconnect = listener; } },
          postMessage(message) { port.sent.push(message); },
        };
        ports.push(port);
        return port;
      },
    },
  };
  function emit(changes, area) {
    for (const listener of listeners) listener(changes, area);
  }
  const context = vm.createContext({
    chrome,
    navigator: { userAgent: 'Chrome/1' },
    importScripts: name => run(name, context),
  });
  run('background.js', context);
  return { local, ports, alarms, emit, rulesEnabled: () => rulesEnabled };
}

function sendPolicy(port, enabled, x_selectors = []) {
  port.message({ type: 'policy', policy: { enabled, x_selectors } });
  return flush();
}

test('sin elección en Cicerón, el bloqueo queda activo y aplica los selectores', async () => {
  const x = setup();
  await flush();
  await sendPolicy(x.ports[0], null, ['aside']);
  assert.equal(x.local.ciceron_connected, true);
  assert.deepEqual(x.local.x_selectors, ['aside']);
  assert.equal(x.rulesEnabled(), true);
});

test('solo las órdenes del puente pausan y reactivan el bloqueo', async () => {
  const x = setup();
  await flush();
  const port = x.ports[0];
  x.emit({ enabled: { newValue: false } }, 'sync');
  await flush();
  assert.equal(x.rulesEnabled(), true);
  await sendPolicy(port, false);
  assert.equal(x.local.ciceron_enabled, false);
  assert.equal(x.rulesEnabled(), false);
  assert.equal(port.sent.at(-1).enabled, false);
  await sendPolicy(port, true);
  assert.equal(x.local.ciceron_enabled, true);
  assert.equal(x.rulesEnabled(), true);
  assert.equal(port.sent.at(-1).enabled, true);
});

test('la desconexión conserva la última orden y la reconexión admite cambios', async () => {
  const x = setup();
  await flush();
  await sendPolicy(x.ports[0], false);
  x.ports[0].disconnect();
  x.emit({ enabled: { newValue: true } }, 'sync');
  await flush();
  assert.equal(x.local.ciceron_connected, false);
  assert.equal(x.rulesEnabled(), false);
  x.alarms[0]({ name: 'ciceron-reconnect' });
  await sendPolicy(x.ports[1], null);
  assert.equal(x.rulesEnabled(), false);
  await sendPolicy(x.ports[1], true);
  assert.equal(x.rulesEnabled(), true);
});

test('rechaza selectores que contengan declaraciones CSS', async () => {
  const x = setup();
  await flush();
  await sendPolicy(x.ports[0], false, ['body{display:none}']);
  assert.equal(x.local.ciceron_connected, false);
  assert.equal(x.rulesEnabled(), true);
});
