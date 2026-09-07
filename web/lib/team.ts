/**
 * Reading a workspace's team.
 *
 * The queries only. What a role may do to another role is `lib/roles.ts`,
 * which is pure and therefore importable from a client component -- this
 * file is not, because `lib/api.ts` reaches `next/headers`.
 */

import { api } from "@/lib/api";
import type { Invitation, InvitationPreview, Member } from "@/lib/types";

export function listMembers(workspaceId: string) {
  // Unpaginated at the API on purpose: a workspace's team is people, and
  // the plans this is built for cap that in the low tens.
  return api<Member[]>(`/workspaces/${workspaceId}/members`);
}

/**
 * Every invitation this workspace has sent, newest first.
 *
 * Admin-only at the API, and rightly: it is a list of the addresses of
 * people being recruited, which is not everybody's business.
 */
export function listInvitations(workspaceId: string) {
  return api<Invitation[]>(`/workspaces/${workspaceId}/invitations`);
}

export function previewInvitation(token: string) {
  // No bearer token: whoever is reading this may not have an account yet,
  // which is the point of having been invited.
  return api<InvitationPreview>(`/invitations/${token}`, { anonymous: true });
}
