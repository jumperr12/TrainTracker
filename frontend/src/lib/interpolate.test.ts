import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { LatLon } from "../api/types";
import { bearingDeg, cumulative, haversineM, interpolateAlong } from "./interpolate";

interface Case {
  name: string;
  path: LatLon[];
  fraction: number;
  expected: [number, number, number];
}

const cases: Case[] = JSON.parse(
  readFileSync(new URL("../../../backend/tests/fixtures/interp_cases.json", import.meta.url), "utf-8"),
);

const angleDiff = (a: number, b: number) => Math.abs(((a - b + 540) % 360) - 180);

describe("interpolateAlong matches the Python implementation", () => {
  for (const c of cases) {
    it(c.name, () => {
      const cum = cumulative(c.path);
      const p = interpolateAlong(c.path, cum, c.fraction * cum[cum.length - 1]);
      expect(p.lat).toBeCloseTo(c.expected[0], 6);
      expect(p.lon).toBeCloseTo(c.expected[1], 6);
      expect(angleDiff(p.bearing, c.expected[2])).toBeLessThan(0.01);
    });
  }
});

describe("geodesy basics", () => {
  it("Warszawa Centralna to Kraków Główny is ~252 km", () => {
    const d = haversineM(52.2289, 21.0032, 50.0677, 19.9476);
    expect(d).toBeGreaterThan(250_000);
    expect(d).toBeLessThan(255_000);
  });

  it("bearing east is 90°", () => {
    expect(bearingDeg(52, 20, 52, 21)).toBeCloseTo(89.6, 0);
  });

  it("clamps outside the path", () => {
    const path: LatLon[] = [
      [52, 20],
      [52, 20.1],
    ];
    const cum = cumulative(path);
    expect(interpolateAlong(path, cum, -10).lon).toBe(20);
    expect(interpolateAlong(path, cum, 1e9).lon).toBeCloseTo(20.1, 9);
  });
});
