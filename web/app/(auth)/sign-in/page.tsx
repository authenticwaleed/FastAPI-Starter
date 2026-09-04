import type { Metadata } from "next";
import Link from "next/link";

import { SignInForm } from "./sign-in-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export const metadata: Metadata = { title: "Sign in" };

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; reset?: string }>;
}) {
  const { next, reset } = await searchParams;

  return (
    <Card>
      <CardHeader>
        <CardTitle><h1>Sign in</h1></CardTitle>
        <CardDescription>Pick up where your team left off.</CardDescription>
      </CardHeader>

      <CardContent>
        {/*
          `next` is validated in the action rather than here. A path that
          arrives in a query string is somebody else's input wherever it is
          read, and one place deciding what is safe to redirect to beats two.
        */}
        <SignInForm next={next ?? "/"} justReset={reset === "1"} />
      </CardContent>

      <CardFooter className="text-muted-foreground justify-center text-sm">
        No account?
        <Link
          href="/register"
          className="text-foreground ml-1 underline underline-offset-4"
        >
          Create one
        </Link>
      </CardFooter>
    </Card>
  );
}
