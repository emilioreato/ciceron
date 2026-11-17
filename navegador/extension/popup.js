const button = document.getElementById("open");
const error = document.getElementById("error");

button.addEventListener("click", async () => {
  button.disabled = true;
  error.hidden = true;
  try {
    const result = await chrome.runtime.sendNativeMessage("com.ciceron.browser", { type: "open-ciceron" });
    if (result?.ok === true) {
      window.close();
      return;
    }
  } catch {
    // The bridge may be unavailable until Cicerón is installed or repaired.
  }
  error.hidden = false;
  button.disabled = false;
});
