import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const alertVariants = cva(
  "group/alert relative grid w-full gap-0.5 rounded-md border px-3 py-2.5 text-left text-sm has-data-[slot=alert-action]:relative has-data-[slot=alert-action]:pr-18 has-[>svg]:grid-cols-[auto_1fr] has-[>svg]:gap-x-2 *:[svg]:row-span-2 *:[svg]:translate-y-0.5 *:[svg]:text-current *:[svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "border-border bg-card text-card-foreground",
        /*
         * Four tones, each a wash of its own ink.
         *
         * The one that matters is `info`, and it exists for a single
         * distinction the API makes and this client kept losing: a 402 is
         * the plan being in the way, not the person. Rendering that in the
         * same red as a 403 tells somebody they are not allowed to do
         * something they could do by upgrading.
         */
        destructive:
          "border-destructive/25 bg-destructive/8 text-destructive *:data-[slot=alert-description]:text-destructive/90 *:[svg]:text-current dark:bg-destructive/12",
        warning:
          "border-warning/25 bg-warning/8 text-warning *:data-[slot=alert-description]:text-warning/90 *:[svg]:text-current dark:bg-warning/12",
        success:
          "border-success/25 bg-success/8 text-success *:data-[slot=alert-description]:text-success/90 *:[svg]:text-current dark:bg-success/12",
        info: "border-info/25 bg-info/8 text-info *:data-[slot=alert-description]:text-info/90 *:[svg]:text-current dark:bg-info/12",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

/*
 * The role is the caller's, not this component's.
 *
 * It used to hardcode `role="alert"`, which made every one of these a live
 * region -- announced out of order, on load, whether or not anything had
 * happened. That is right for a refusal that just came back from a server
 * action and wrong for a sentence that was on the page the whole time.
 *
 * It also had a second effect worth knowing about: a static banner
 * rendered above a form became the first `alert` on the page, so anything
 * looking for "the refusal" -- a screen reader, or a test -- found the
 * banner instead.
 *
 * So: `role="alert"` for something that has just gone wrong, `role="status"`
 * for something that has just changed, and nothing at all for standing
 * copy.
 */
function Alert({
  className,
  variant,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  return (
    <div
      data-slot="alert"
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  )
}

function AlertTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-title"
      className={cn(
        "font-medium group-has-[>svg]/alert:col-start-2 [&_a]:underline [&_a]:underline-offset-3 [&_a]:hover:text-foreground",
        className
      )}
      {...props}
    />
  )
}

function AlertDescription({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-description"
      className={cn(
        "text-sm text-balance text-muted-foreground md:text-pretty [&_a]:underline [&_a]:underline-offset-3 [&_a]:hover:text-foreground [&_p:not(:last-child)]:mb-4",
        className
      )}
      {...props}
    />
  )
}

function AlertAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-action"
      className={cn("absolute top-2 right-2", className)}
      {...props}
    />
  )
}

export { Alert, AlertTitle, AlertDescription, AlertAction }
