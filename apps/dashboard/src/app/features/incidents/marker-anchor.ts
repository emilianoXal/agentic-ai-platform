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
