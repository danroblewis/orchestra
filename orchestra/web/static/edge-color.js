// The colour of an edge from the colour of the node it belongs to (a design by a visualisation
// review, 2026-10-25): in OKLCH, every edge of a kind gets the same lightness and a share of its
// node's chroma, keeping the node's hue. So yellow does not glare and blue does not sink, edges sit
// behind their nodes, and full chroma stays for the nodes (and gold for a highlighted loop).
//   publish (machine → event type): the publishing machine's colour
//   listen  (event type → machine): the listening machine's colour (drawn dashed)
//   unseen  (not on the bus in the last 24 h): a near-grey with the machine's tint
//   hover:  the node's own colour
const EDGE_TONE = {
  dark:  { publish: [0.66, 0.55], listen: [0.74, 0.40], unseen: [0.42, 0.12] },
  light: { publish: [0.55, 0.60], listen: [0.62, 0.45], unseen: [0.78, 0.12] },
};
function edgeColor(hex, mode, theme = "dark") {
  if (mode === "hover") return hex;
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255].map((v) => {
    v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  const [L, k] = EDGE_TONE[theme][mode];
  for (let f = k; ; f *= 0.95) {                 // less chroma until it is in the sRGB gamut
    const A = a * f, B = bb * f;
    const l3 = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
    const m3 = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
    const s3 = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
    const rgb = [
      4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
      -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
      -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3,
    ];
    if (f < 0.01 || rgb.every((v) => v >= -1e-4 && v <= 1 + 1e-4))
      return "#" + rgb.map((v) => {
        v = Math.min(1, Math.max(0, v));
        v = v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
        return Math.round(v * 255).toString(16).padStart(2, "0");
      }).join("");
  }
}
