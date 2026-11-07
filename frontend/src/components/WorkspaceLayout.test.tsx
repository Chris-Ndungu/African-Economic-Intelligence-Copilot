import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "@/App";

describe("WorkspaceLayout", () => {
  it("renders the header with the product name and a shadcn button", () => {
    render(<App />);

    const header = screen.getByRole("banner");
    expect(header).toHaveTextContent("African Economic Intelligence Copilot");
    const button = screen.getByRole("button", { name: "New investigation" });
    expect(header).toContainElement(button);
    expect(button).toHaveAttribute("data-slot", "button");
    expect(button).toHaveClass("bg-primary", "text-primary-foreground");
  });

  it("renders a sidebar and a main panel with placeholder text", () => {
    render(<App />);

    const sidebar = screen.getByRole("complementary", { name: "Selection" });
    const main = screen.getByRole("main", { name: "Workspace" });
    expect(sidebar).toHaveTextContent(/countries, indicators and periods/i);
    expect(main).toHaveTextContent(/start an investigation/i);
  });

  it("stacks the sidebar above the main panel below the md breakpoint", () => {
    render(<App />);

    const sidebar = screen.getByRole("complementary", { name: "Selection" });
    const main = screen.getByRole("main", { name: "Workspace" });
    const container = sidebar.parentElement!;
    expect(main.parentElement).toBe(container);
    expect(container.firstElementChild).toBe(sidebar);
    expect(container).toHaveClass("flex-col", "md:flex-row");
  });
});
