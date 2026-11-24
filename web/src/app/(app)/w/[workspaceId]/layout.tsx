import { WorkspaceShell } from "@/components/app/workspace-context";

export default function WorkspaceLayout({ children }: LayoutProps<"/w/[workspaceId]">) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
