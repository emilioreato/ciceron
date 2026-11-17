let ciceronPort = null;
let policyChain = Promise.resolve();
const alarmName = 'ciceron-reconnect';

async function applyCiceronPolicy(message, port) {
  if (!message || message.type !== 'policy' || !message.policy || typeof message.policy !== 'object') return;
  if (ciceronPort !== port) return;
  const policy = message.policy;
  if (policy.enabled !== null && typeof policy.enabled !== 'boolean') return;
  if (!Array.isArray(policy.x_selectors) || policy.x_selectors.length > 25 ||
      policy.x_selectors.some(s => typeof s !== 'string' || !s.trim() || s.length > 300 || /[{};@\r\n]/.test(s))) return;
  // Null significa que Cicerón todavía no eligió un estado de bloqueo.
  const update = { ciceron_connected: true, x_selectors: policy.x_selectors };
  if (policy.enabled !== null) update.ciceron_enabled = policy.enabled;
  await chrome.storage.local.set(update);
  await queuePolicySync();
}

async function browserLabel() {
  try { if (navigator.brave && await navigator.brave.isBrave()) return 'Brave'; } catch {}
  if (/Edg\//.test(navigator.userAgent)) return 'Edge';
  if (/Chrome\//.test(navigator.userAgent)) return 'Chrome';
  return 'Chromium';
}
function connectCiceron() {
  if (ciceronPort) return;
  try {
    const port = chrome.runtime.connectNative('com.ciceron.browser');
    ciceronPort = port;
    port.onMessage.addListener(message => { policyChain = policyChain.then(() => applyCiceronPolicy(message, port)).catch(() => {}); });
    port.onDisconnect.addListener(() => {
      if (ciceronPort !== port) return;
      ciceronPort = null;
      chrome.storage.local.set({ ciceron_connected: false }).catch(() => {});
    });
    browserLabel().then(browser => { if (ciceronPort === port) { port.postMessage({ type: 'hello', browser }); reportStatus(); } }).catch(() => {});
  } catch {
    ciceronPort = null;
    chrome.storage.local.set({ ciceron_connected: false }).catch(() => {});
  }
}
chrome.alarms.create(alarmName, { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === alarmName && !ciceronPort) connectCiceron(); });
chrome.storage.local.set({ ciceron_connected: false }).then(connectCiceron, connectCiceron);

function reportStatus() {
  const port = ciceronPort;
  if (!port) return;
  chrome.storage.local.get({ ciceron_applied: null, ciceron_rule_error: false }).then(value => {
    if (ciceronPort === port) port.postMessage({type: 'status', enabled: value.ciceron_applied, error: value.ciceron_rule_error === true});
  }).catch(() => {});
}
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && (changes.ciceron_applied || changes.ciceron_rule_error)) reportStatus();
});
