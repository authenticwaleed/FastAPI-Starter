import { ConsoleLink } from "@/components/console/console-link";
import { Pagination } from "@/components/pagination";

/**
 * Paging on the console, which is the shared component with prefetching
 * off.
 *
 * That is the only difference and it is not a small one: Next prefetches a
 * link that enters the viewport, every console read writes a row to the
 * platform audit log, and "Next" sitting at the bottom of a list is a link
 * that enters the viewport on every single one of these screens.
 */
export function ConsolePages({
  page,
  total,
  pageSize,
  href,
  noun,
}: {
  page: number;
  total: number;
  pageSize: number;
  href: (page: number) => string;
  noun: string;
}) {
  return (
    <Pagination
      page={page}
      total={total}
      pageSize={pageSize}
      href={href}
      noun={noun}
      as={ConsoleLink}
    />
  );
}
