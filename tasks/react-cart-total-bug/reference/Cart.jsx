import { useState } from "react";

const INITIAL_ITEMS = [
  { id: "sku-1", name: "Wireless Mouse", price: 18, qty: 1 },
  { id: "sku-2", name: "Mechanical Keyboard", price: 24, qty: 1 },
];

export function Cart() {
  const [items, setItems] = useState(INITIAL_ITEMS);

  const subtotal = items.reduce((sum, it) => sum + it.price * it.qty, 0);

  const setQty = (id, delta) => {
    setItems((prev) =>
      prev.map((it) =>
        it.id === id ? { ...it, qty: Math.max(1, it.qty + delta) } : it
      )
    );
  };

  return (
    <div>
      <header>
        <span data-testid="subtotal">${subtotal}</span>
      </header>

      {subtotal >= 50 && (
        <div data-testid="free-shipping-banner">
          You've unlocked free shipping!
        </div>
      )}

      <ul>
        {items.map((it) => (
          <li key={it.id}>
            <span>{it.name}</span>
            <button
              data-testid={`dec-${it.id}`}
              onClick={() => setQty(it.id, -1)}
            >
              -
            </button>
            <span data-testid={`qty-${it.id}`}>{it.qty}</span>
            <button
              data-testid={`inc-${it.id}`}
              onClick={() => setQty(it.id, 1)}
            >
              +
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
