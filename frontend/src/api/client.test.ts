import { describe, expect, it } from "vitest";
import { ApiError, toApiError } from "./client";

describe("toApiError", () => {
  it("maps the backend error envelope", () => {
    const e = toApiError({ response: { status: 409, data: { error: { code: "model_not_trained", message: "No model", hint: "Train it" } } } });
    expect(e).toBeInstanceOf(ApiError);
    expect(e.code).toBe("model_not_trained");
    expect(e.hint).toBe("Train it");
    expect(e.status).toBe(409);
  });
  it("keeps validation details", () => {
    const e = toApiError({ response: { status: 422, data: { error: { code: "validation_error", message: "bad", details: [{ field: "scenario.seed", message: "x" }] } } } });
    expect(e.details?.[0].field).toBe("scenario.seed");
  });
  it("explains an unreachable backend without leaking internals", () => {
    const e = toApiError({ message: "Network Error" });
    expect(e.code).toBe("network_error");
    expect(e.message).toMatch(/Cannot reach the NexFlow API/);
  });
  it("handles non-JSON server errors", () => {
    const e = toApiError({ response: { status: 502, data: "<html>" } });
    expect(e.code).toBe("http_error");
    expect(e.message).toContain("502");
  });
});
