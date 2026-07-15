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
      this._panes = {};
      if (this._container) {
        if (!this._container.style.position) this._container.style.position = "relative";
        const overlay = document.createElement("div");
        overlay.className = "leaflet-overlay-pane";
        overlay.style.position = "absolute";
        overlay.style.inset = "0";
        this._container.appendChild(overlay);
        this._panes.overlayPane = overlay;
      }
    }
    fitBounds() { return this; }
    on() { return this; }
    off() { return this; }
    getZoom() { return 0; }
    getContainer() { return this._container; }
    createPane(name) {
      if (this._panes[name]) return this._panes[name];
      const pane = document.createElement("div");
      pane.className = "leaflet-pane";
      pane.dataset.pane = name;
      pane.style.position = "absolute";
      pane.style.inset = "0";
      this._container?.appendChild(pane);
      this._panes[name] = pane;
      return pane;
    }
    getPane(name) { return this._panes[name] || null; }
    latLngToContainerPoint(latlng) {
      return {
        x: 60 + Number(latlng?.lng || 0),
        y: 60 - Number(latlng?.lat || 0),
      };
    }
    containerPointToLatLng(point) {
      return {
        lat: -(Number(point?.[1] || 0) - 60),
        lng: Number(point?.[0] || 0) - 60,
      };
    }
    setView() { return this; }
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
    dragging = { disable() {}, enable() {} };
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
          const pane = options.pane ? map.getPane(options.pane) : null;
          (pane || map._container)?.appendChild(el);
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
