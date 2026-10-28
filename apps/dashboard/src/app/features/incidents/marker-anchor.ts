/** MapLibre anchor that keeps the dot's center on the incident at every zoom. */
export const MARKER_ANCHOR = 'center' as const;

/** Options passed to MapLibre so the marker element stays pinned at every zoom. */
export function incidentMarkerOptions(element: HTMLElement): {
  element: HTMLElement;
  anchor: typeof MARKER_ANCHOR;
  offset: [number, number];
  subpixelPositioning: true;
} {
  return {
    element,
    anchor: MARKER_ANCHOR,
    offset: [0, 0],
    subpixelPositioning: true,
  };
}

const EDGE_ANCHORS = new Set(['top', 'bottom', 'left', 'right']);
const CORNER_ANCHORS = new Set(['top-left', 'top-right', 'bottom-left', 'bottom-right']);

/** Pixels between the geographic anchor and the center of the marker box. */
export function markerCenterOffsetPx(sizePx: number, anchor: string = MARKER_ANCHOR): number {
  if (anchor === 'center') return 0;
  if (CORNER_ANCHORS.has(anchor)) return Math.hypot(sizePx / 2, sizePx / 2);
  if (EDGE_ANCHORS.has(anchor)) return sizePx / 2;
  return sizePx / 2;
}

/**
 * Meters the dot's center sits away from the incident coordinate.
 * A fixed pixel offset is a long distance when zoomed out and a short one when zoomed in.
 */
export function markerCenterDriftMeters(
  sizePx: number,
  zoom: number,
  latitude: number,
  anchor: string = MARKER_ANCHOR,
): number {
  const metersPerPixel =
    (156543.03392 * Math.cos((latitude * Math.PI) / 180)) / 2 ** zoom;
  return markerCenterOffsetPx(sizePx, anchor) * metersPerPixel;
}
