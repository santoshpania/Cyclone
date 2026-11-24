import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="mx-auto flex max-w-2xl flex-1 flex-col justify-center gap-6 px-4 py-24">
      <h1 className="text-4xl font-semibold tracking-tight">Cyclone</h1>
      <p className="text-lg text-muted-foreground">
        See which businesses in your territory already buy from you, which match your ideal customer and nobody covers
        yet, and how to reach them.
      </p>
      <div>
        <Link href="/workspaces" className={buttonVariants({ size: "lg" })}>
          Open Cyclone
        </Link>
      </div>
    </main>
  );
}
