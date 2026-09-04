import type { Metadata } from "next";
import Link from "next/link";

import { ResetForm } from "./reset-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export const metadata: Metadata = { title: "Set a new password" };

export default async function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;

  if (!token) {
    return (
      <Card>
        <CardHeader>
          <CardTitle><h1>This link is incomplete</h1></CardTitle>
          <CardDescription>
            It is missing the part that proves it is yours. Ask for another and
            follow it without editing the address.
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <Link
            href="/forgot-password"
            className="text-sm underline underline-offset-4"
          >
            Send another link
          </Link>
        </CardFooter>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle><h1>Set a new password</h1></CardTitle>
        <CardDescription>Then sign in with it.</CardDescription>
      </CardHeader>

      <CardContent>
        <ResetForm token={token} />
      </CardContent>
    </Card>
  );
}
