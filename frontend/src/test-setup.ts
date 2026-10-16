// jsdom lacks SVG geometry APIs that Leaflet probes for; provide minimal shims so vector layers render.
(SVGElement.prototype as any).createSVGRect = () => ({});
Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 800 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 600 });
