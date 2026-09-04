import type { Metadata } from "next";
import Link from "next/link";

import { RegisterForm } from "./register-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export const metadata: Metadata = { title: "Create an account" };

export default function RegisterPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle><h1>Create an account</h1></CardTitle>
        <CardDescription>
          You will be signed in straight away. Confirming your address can wait.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <RegisterForm />
      </CardContent>

      <CardFooter className="text-muted-foreground justify-center text-sm">
        Already have one?
        <Link
          href="/sign-in"
          className="text-foreground ml-1 underline underline-offset-4"
        >
          Sign in
        </Link>
      </CardFooter>
    </Card>
  );
}
