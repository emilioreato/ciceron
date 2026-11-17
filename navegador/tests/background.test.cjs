const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const dir = path.join(__dirname, '..', 'extension');
const source = fs.readFileSync(path.join(dir, 'background.js'), 'utf8');

function setup(initial, legacy = {}) {
  const handlers = {};
  const calls = [];
  const local = { ...initial };
  const chrome = {
    declarativeNetRequest: {
      updateEnabledRulesets: async args => calls.push(JSON.parse(JSON.stringify(args))),
    },
    storage: {
      sync: {
        get: async defaults => ({ ...defaults, ...legacy }),
      },
      local: {
        get: async defaults => ({ ...defaults, ...local }),
        set: async data => Object.assign(local, data),
      },
      onChanged: { addListener: fn => { handlers.changed = fn; } },
    },
    runtime: {
      onInstalled: { addListener: fn => { handlers.installed = fn; } },
      onStartup: { addListener: fn => { handlers.startup = fn; } },
    },
  };
  vm.runInNewContext(source, { chrome });
  return { handlers, calls, local };
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('conserva al iniciar la pausa recibida de Cicerón', async () => {
  const x = setup({ ciceron_enabled: false });
  x.handlers.startup(); await flush();
  assert.equal(x.local.ciceron_applied, false);
  assert.deepEqual(x.calls.at(-1), { enableRulesetIds: [], disableRulesetIds: ['hard_block'] });
});
test('activa el conjunto de reglas cuando la protección está activa', async () => {
  const x = setup({ ciceron_enabled: true });
  x.handlers.startup(); await flush();
  assert.deepEqual(x.calls.at(-1), { enableRulesetIds: ['hard_block'], disableRulesetIds: [] });
  assert.equal(x.local.ciceron_applied, true);
  assert.equal(x.local.ciceron_rule_error, false);
});
test('la actualización ignora una pausa local de la versión anterior', async () => {
  const x = setup({}, { enabled: false, policyVersion: 3 });
  x.handlers.installed(); await flush();
  assert.equal(x.local.ciceron_applied, true);
  assert.deepEqual(x.calls.at(-1), { enableRulesetIds: ['hard_block'], disableRulesetIds: [] });
});
test('el manifiesto incluye reglas y scripts locales sin ampliar permisos', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'), 'utf8'));
  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(manifest.permissions, ['storage', 'declarativeNetRequest', 'nativeMessaging', 'alarms']);
  assert.ok(manifest.content_scripts.some(item => item.js.includes('content.js')));
  assert.ok(manifest.declarative_net_request.rule_resources.some(item => item.id === 'hard_block'));
});
