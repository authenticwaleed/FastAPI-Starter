import type { Metadata } from "next";
import Link from "next/link";

import { VerifyForm } from "./verify-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export const metadata: Metadata = { title: "Confirm your address" };

export default async function VerifyEmailPage({
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
            It is missing the part that proves it is yours. Sign in and ask for
            another from your account.
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <Link href="/sign-in" className="text-sm underline underline-offset-4">
            Sign in
          </Link>
        </CardFooter>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle><h1>Confirm your address</h1></CardTitle>
        <CardDescription>
          One click, and we know we can reach you.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <VerifyForm token={token} />
      </CardContent>
    </Card>
  );
}
