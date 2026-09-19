/**
 * Minimal typing for the single function used from d3-geo-projection.
 * The package ships no types, and only `geoProject` is needed: it runs a
 * GeoJSON object through d3's projection stream, which both projects the
 * coordinates and clips them at the antimeridian.
 */
declare module "d3-geo-projection" {
  import type { GeoProjection } from "d3-geo";
  import type { GeoGeometryObjects } from "d3-geo";

  export function geoProject<T extends GeoGeometryObjects | { type: string }>(
    object: T,
    projection: GeoProjection,
  ): T | null;
}
