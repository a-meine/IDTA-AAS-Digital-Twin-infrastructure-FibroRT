window.onload = function() {
  fetch("/v3/api-docs")
    .then(function(response) { return response.text(); })
    .then(function(text) {
      var spec;
      try {
        var raw = JSON.parse(text);
        if (typeof raw === "string") {
          spec = JSON.parse(atob(raw));
        } else {
          spec = raw;
        }
      } catch (e) {
        spec = JSON.parse(text);
      }
      window.ui = SwaggerUIBundle({
        spec: spec,
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset
        ],
        plugins: [
          SwaggerUIBundle.plugins.DownloadUrl
        ],
        layout: "StandaloneLayout"
      });
    });
};
