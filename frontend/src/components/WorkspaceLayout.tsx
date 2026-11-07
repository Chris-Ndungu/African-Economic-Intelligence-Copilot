import { Button } from "@/components/ui/button";

const PRODUCT_NAME = "African Economic Intelligence Copilot";

/**
 * The empty investigation workspace: a header, a selection sidebar and a
 * main panel. Below the `md` breakpoint the sidebar stacks above the main
 * panel so the page never scrolls sideways on a phone.
 */
export function WorkspaceLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <h1 className="min-w-0 text-lg font-semibold">{PRODUCT_NAME}</h1>
        <Button size="sm">New investigation</Button>
      </header>
      <div className="flex min-w-0 flex-1 flex-col md:flex-row">
        <aside
          aria-label="Selection"
          className="border-b bg-muted p-4 md:w-72 md:shrink-0 md:border-r md:border-b-0"
        >
          <p className="text-sm text-muted-foreground">
            Countries, indicators and periods will be chosen here.
          </p>
        </aside>
        <main aria-label="Workspace" className="min-w-0 flex-1 p-4">
          <p className="text-sm text-muted-foreground">
            Ask a question or pick a selection to start an investigation.
          </p>
        </main>
      </div>
    </div>
  );
}
