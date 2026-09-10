import * as React from "react"
import { cn } from "cn"

/**
 * A real select element, styled to match the rest of the fields.
 *
 * Not the Radix combobox this project also has installed and has never
 * used, and that is deliberate rather than laziness: every form in this
 * client is a `<form action={serverAction}>` with no submit handler, so the
 * controls have to be ones the platform posts on their own. A combobox is
 * a button and a listbox with a hidden input behind it -- more markup, more
 * JavaScript, and a worse result on a phone, where the native picker is
 * the thing people already know.
 *
 * Twenty-two files styled these by hand, at three different heights
 * (`h-7`, `h-8`, `h-9`), some with a stray `shadow-xs`, all of them
 * `bg-background` -- which, now that the page is a shade off white, made
 * every one of them read as a hole rather than as a control.
 *
 * The arrow is the browser's. Replacing it means `appearance: none` and a
 * background image, which is a second colour to keep in step with the
 * theme in exchange for a triangle nobody has ever complained about.
 *
 * No width, deliberately. A grid item stretches to its column without one,
 * and half of these sit in a flex row beside a button -- where `w-full`
 * would take the row and squash the button off the end of it.
 */
function NativeSelect({
  className,
  ...props
}: React.ComponentProps<"select">) {
  return (
    <select
      data-slot="native-select"
      className={cn(
        "h-8 rounded-md border border-input bg-card px-2 text-sm transition-colors outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-70 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
        className
      )}
      {...props}
    />
  )
}

export { NativeSelect }
