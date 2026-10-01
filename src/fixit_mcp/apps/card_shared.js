  // Pure, DOM-free by design so it's directly testable (e.g. via a Node
  // driver script) without a browser -- see tests/unit/test_diagnose_card.py.
  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function listHtml(items) {
    return (items || []).map(function (item) { return "<li>" + esc(item) + "</li>"; }).join("");
  }

