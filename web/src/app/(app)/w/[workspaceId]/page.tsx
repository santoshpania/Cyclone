"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

export default function WorkspaceHome() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const router = useRouter();
  useEffect(() => router.replace(`/w/${workspaceId}/imports`), [router, workspaceId]);
  return null;
}
