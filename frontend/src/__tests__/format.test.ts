import { describe, expect, it } from "vitest";
import {
  compactUsd,
  exactUsd,
  hsLabel,
  percent,
  periodLabel,
  shortPeriodLabel,
  signedPercent,
  unitValue,
} from "../lib/format";

describe("compactUsd", () => {
  it("uses the documented magnitude suffixes", () => {
    expect(compactUsd(1_240)).toBe("$1.24K");
    expect(compactUsd(1_240_000)).toBe("$1.24M");
    expect(compactUsd(1_240_000_000)).toBe("$1.24B");
    expect(compactUsd(1.24e12)).toBe("$1.24T");
  });

  it("keeps small values unabbreviated", () => {
    expect(compactUsd(842)).toBe("$842");
  });

  it("renders negatives with a leading sign", () => {
    expect(compactUsd(-1_240_000_000)).toBe("-$1.24B");
  });

  it("renders missing data as an em dash, never as zero", () => {
    expect(compactUsd(null)).toBe("—");
    expect(compactUsd(undefined)).toBe("—");
    expect(compactUsd(0)).toBe("$0");
  });
});

describe("exactUsd", () => {
  it("gives full precision for tooltips", () => {
    expect(exactUsd(48_203_292_847)).toBe("$48,203,292,847");
  });

  it("says so when there is no reported data", () => {
    expect(exactUsd(null)).toBe("No reported data");
  });
});

describe("percent", () => {
  it("uses one decimal by default", () => {
    expect(percent(0.6842)).toBe("68.4%");
  });

  it("never renders a non-zero share as 0.00%", () => {
    expect(percent(0.0001)).toBe("0.01%");
    expect(percent(0.0000004)).toBe("<0.01%");
    expect(percent(0.0000004)).not.toBe("0.00%");
    expect(percent(-0.0000004)).toBe(">-0.01%");
  });

  it("renders a true zero plainly", () => {
    expect(percent(0)).toBe("0.0%");
  });

  it("renders missing as an em dash", () => {
    expect(percent(null)).toBe("—");
  });

  it("signs a change", () => {
    expect(signedPercent(0.074)).toBe("+7.4%");
    expect(signedPercent(-0.074)).toBe("-7.4%");
    expect(signedPercent(null)).toBe("—");
  });
});

describe("periods", () => {
  it("expands a monthly period", () => {
    expect(periodLabel("202506")).toBe("Jun 2025");
    expect(periodLabel("202601")).toBe("Jan 2026");
  });

  it("leaves an annual period alone", () => {
    expect(periodLabel("2025")).toBe("2025");
  });

  it("abbreviates for a dense axis", () => {
    expect(shortPeriodLabel("202506")).toBe("Jun");
    expect(shortPeriodLabel("202601")).toBe("Jan 26");
  });
});

describe("hs codes", () => {
  it("preserves leading zeros", () => {
    expect(hsLabel("01")).toBe("01");
    expect(hsLabel("0101")).toBe("0101");
  });
});

describe("unit value", () => {
  it("labels dollars per kilogram", () => {
    expect(unitValue(2.5)).toBe("$2.50/kg");
    expect(unitValue(0.004)).toBe("$0.004/kg");
    expect(unitValue(2500)).toBe("$2.5k/kg");
    expect(unitValue(null)).toBe("—");
  });
});
