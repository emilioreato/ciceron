const RULESET_ID = "hard_block";

async function setHardBlockEnabled(enabled) {
  try {
    await chrome.declarativeNetRequest.updateEnabledRulesets({
      enableRulesetIds: enabled ? [RULESET_ID] : [],
      disableRulesetIds: enabled ? [] : [RULESET_ID],
    });
    await chrome.storage.local.set({ ciceron_applied: enabled, ciceron_rule_error: false });
  } catch (error) {
    await chrome.storage.local.set({ ciceron_applied: null, ciceron_rule_error: true }).catch(() => {});
    throw error;
  }
}

async function syncPolicy() {
  const { ciceron_enabled } = await chrome.storage.local.get({ ciceron_enabled: true });
  await setHardBlockEnabled(ciceron_enabled !== false);
}

let policySync = Promise.resolve();
function queuePolicySync() {
  policySync = policySync.then(syncPolicy).catch(() => {});
  return policySync;
}
chrome.runtime.onInstalled.addListener(queuePolicySync);
chrome.runtime.onStartup.addListener(queuePolicySync);
queuePolicySync();
if (typeof importScripts === "function") importScripts("bridge.js");
