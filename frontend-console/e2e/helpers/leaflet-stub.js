/**
 * Leaflet CDN stub for E2E.
 *
 * The production app loads Leaflet from unpkg. E2E must not depend on external
 * network availability, so map specs install this route before page navigation.
 */

const LEAFLET_STUB = `
(() => {
  if (window.L) return;

  class StubMap {
    constructor(container) {
      this._container = typeof container === "string"
        ? document.getElementById(container)
        : container;
      this._layers = [];
      if (this._container) {
        if (!this._container.style.position) this._container.style.position = "relative";
        const overlay = document.createElement("div");
        overlay.className = "leaflet-overlay-pane";
        overlay.style.position = "absolute";
        overlay.style.inset = "0";
        this._container.appendChild(overlay);
      }
    }
    fitBounds() { return this; }
    on() { return this; }
    getZoom() { return 0; }
    latLngToContainerPoint() { return { x: 60, y: 60 }; }
    eachLayer(callback) { this._layers.slice().forEach(callback); }
    removeLayer(layer) {
      this._layers = this._layers.filter((item) => item !== layer);
      if (layer && layer._el) layer._el.remove();
    }
    closePopup() { return this; }
    remove() {
      this._layers.forEach((layer) => {
        if (layer && layer._el) layer._el.remove();
      });
      this._layers = [];
      if (this._container) this._container.innerHTML = "";
    }
  }

  window.L = {
    CRS: { Simple: {} },
    map(container) { return new StubMap(container); },
    latLngBounds(bounds) { return bounds; },
    latLng(lat, lng) { return { lat, lng }; },
    divIcon(options) { return options; },
    marker(_latlng, options = {}) {
      return {
        _isMapLabel: false,
        _el: null,
        addTo(map) {
          const el = document.createElement("div");
          el.className = options.icon?.className || "";
          el.innerHTML = options.icon?.html || "";
          this._el = el;
          map._container?.appendChild(el);
          map._layers.push(this);
          return this;
        },
      };
    },
    popup() {
      return {
        setLatLng() { return this; },
        setContent(html) { this.html = html; return this; },
        openOn() { return this; },
      };
    },
  };
})();
`

export async function installLeafletStub(target) {
  if (typeof target.addInitScript === "function") {
    await target.addInitScript({ content: LEAFLET_STUB })
  }

  await target.route("**/leaflet@1.9.4/dist/leaflet.css", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/css",
      body: "",
    })
  })

  await target.route("**/leaflet@1.9.4/dist/leaflet.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: LEAFLET_STUB,
    })
  })
}
