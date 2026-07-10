import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";
import { Cart } from "../src/Cart.jsx";

describe("cart subtotal + free shipping", () => {
  it("updates subtotal when quantity changes and toggles the free-shipping banner", async () => {
    const user = userEvent.setup();
    render(<Cart />);

    // Initial subtotal: 18 + 24 = 42, no banner.
    expect(screen.getByTestId("subtotal")).toHaveTextContent("$42");
    expect(screen.queryByTestId("free-shipping-banner")).toBeNull();

    // Bump the keyboard (sku-2, $24) once -> 18 + 48 = 66 -> banner shows.
    await user.click(screen.getByTestId("inc-sku-2"));

    expect(screen.getByTestId("subtotal")).toHaveTextContent("$66");
    const banner = screen.getByTestId("free-shipping-banner");
    expect(banner).toHaveTextContent("You've unlocked free shipping!");

    // Drop it back down -> 18 + 24 = 42 -> banner gone.
    await user.click(screen.getByTestId("dec-sku-2"));
    expect(screen.getByTestId("subtotal")).toHaveTextContent("$42");
    expect(screen.queryByTestId("free-shipping-banner")).toBeNull();
  });
});
