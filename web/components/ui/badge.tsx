import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"
import { Slot } from "radix-ui"

/*
 * Rectangular, not a pill.
 *
 * A pill reads as a tag -- something applied to a thing. These label
 * *states*, which belong to the thing, and a 6px corner beside a 6px input
 * and a 6px row says so. It also stops a badge from being the roundest
 * object on an otherwise square screen.
 */
const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-md border border-transparent px-1.5 py-0.5 text-xs font-medium whitespace-nowrap transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a]:hover:bg-primary/80",
        secondary:
          "bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80",
        destructive:
          "bg-destructive/10 text-destructive focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:focus-visible:ring-destructive/40 [a]:hover:bg-destructive/20",
        outline:
          "border-border text-foreground [a]:hover:bg-muted [a]:hover:text-muted-foreground",
        /*
         * The three states the client had no colour for and was spelling
         * with `secondary`, `outline` and `destructive` instead -- which
         * is how "past due" and "cancelled" ended up looking alike.
         *
         * Tinted rather than filled. A row of solid badges is the rainbow
         * this design is trying not to be; ink on a 10% wash of itself
         * carries the same meaning and lets the row stay quiet.
         */
        success:
          "bg-success/10 text-success [a]:hover:bg-success/20 dark:bg-success/15",
        warning:
          "bg-warning/10 text-warning [a]:hover:bg-warning/20 dark:bg-warning/15",
        info: "bg-info/10 text-info [a]:hover:bg-info/20 dark:bg-info/15",
        /* For a state that is genuinely uninteresting: archived, ended,
           nothing to do. Quieter than `secondary`, which still reads as a
           thing worth noticing. */
        muted: "bg-muted text-muted-foreground",
        ghost:
          "hover:bg-muted hover:text-muted-foreground dark:hover:bg-muted/50",
        link: "text-primary underline-offset-4 hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
