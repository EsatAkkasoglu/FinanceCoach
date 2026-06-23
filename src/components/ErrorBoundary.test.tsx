import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import i18n from "@/i18n";
import ErrorBoundary from "./ErrorBoundary";

let shouldThrow = true;
function Boom() {
  if (shouldThrow) throw new Error("boom");
  return <div>recovered content</div>;
}

describe("ErrorBoundary", () => {
  beforeEach(async () => {
    shouldThrow = true;
    await i18n.changeLanguage("en");
    // React logs caught render errors to console.error — silence for clean output.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows the localized fallback with a reset button when a child throws", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeTruthy();
    expect(screen.getByRole("button", { name: /try again/i })).toBeTruthy();
  });

  it("recovers when reset is clicked and the child stops throwing", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByText("recovered content")).toBeTruthy();
  });

  it("renders a null fallback (decorative layer) instead of the default card", () => {
    const { container } = render(
      <ErrorBoundary fallback={null}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.queryByText("Something went wrong")).toBeNull();
    expect(container.textContent).toBe("");
  });
});
