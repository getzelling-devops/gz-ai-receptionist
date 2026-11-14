// Normalize Daily's normal remote-room termination before the React SDK reports it as a failure.
const Vapi = require("@vapi-ai/web/dist/vapi.js").default;

module.exports = class WebVoice extends Vapi {
  async cleanup() {
    try { await super.cleanup(); }
    catch (error) {
      if (!/meeting.*ended|meeting-ended|ejection/i.test(String(error?.message || error))) throw error;
    }
  }

  emit(event, ...args) {
    const error = args[0];
    const detail = JSON.stringify(error || {});
    if (event === "error"
        && /meeting.*ended|meeting-ended|ejection/i.test(detail)) {
      return super.emit("call-end");
    }
    return super.emit(event, ...args);
  }
};
