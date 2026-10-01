  // MCP Apps handshake: this view is itself an MCP client talking to the
  // host over postMessage (spec: Communication Protocol). No network
  // fetching anywhere in this file -- all data arrives via postMessage.
  (function () {
    var nextId = 1;
    function sendRequest(method, params) {
      var id = nextId++;
      window.parent.postMessage({ jsonrpc: "2.0", id: id, method: method, params: params }, "*");
      return new Promise(function (resolve, reject) {
        window.addEventListener("message", function listener(event) {
          if (event.data && event.data.id === id) {
            window.removeEventListener("message", listener);
            if (event.data.result) resolve(event.data.result);
            else if (event.data.error) reject(new Error(event.data.error));
          }
        });
      });
    }

    window.addEventListener("message", function (event) {
      var data = event.data;
      if (data && data.method === "ui/notifications/tool-result" && data.params) {
        render(data.params.structuredContent || null);
      }
    });

    sendRequest("ui/initialize", {
      capabilities: {},
      clientInfo: { name: "@@CARD_NAME@@", version: "0.1.0" },
      protocolVersion: "2026-01-26",
    }).catch(function () {
      // Host doesn't speak MCP Apps -- this view is never shown, and the
      // tool's plain content/structuredContent is used as-is (rule: always
      // ship the plain result too, never only the visual).
    });
  })();
